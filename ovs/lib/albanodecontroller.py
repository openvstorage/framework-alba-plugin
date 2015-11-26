# Copyright 2014 iNuron NV
#
# Licensed under the Open vStorage Modified Apache License (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.openvstorage.org/license
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
AlbaNodeController module
"""

import json
import socket
import requests
from subprocess import check_output
from ovs.celery_run import celery
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.diskpartition import DiskPartition
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs.log.logHandler import LogHandler
from ovs.lib.albacontroller import AlbaController
from ovs.lib.disk import DiskController
from ovs.lib.helpers.decorators import add_hooks
from ovs.extensions.generic.sshclient import SSHClient
from ovs.extensions.plugins.albacli import AlbaCLI
logger = LogHandler.get('lib', name='albanode')


class AlbaNodeController(object):
    """
    Contains all BLL related to ALBA nodes
    """

    @staticmethod
    @celery.task(name='albanode.discover')
    def discover():
        """
        Discovers nodes, returning them as a fake, in-memory DataObjectList
        """
        try:
            nodes = {}
            discover_result = check_output('timeout -k 10 5 avahi-browse -rtp _asd_node._tcp 2> /dev/null || true', shell=True)
            # logger.debug('Avahi discovery result:\n{0}'.format(discover_result))
            for entry in discover_result.split('\n'):
                # =;eth1;IPv4;asd_node_ZrdSgl4cYulH7SjvpRuICM3CBcRmfKfp;_asd_node._tcp;local;ovs154233.local;10.100.154.233;8500;
                # split(';') -> [3]  = asd_node_ZrdSgl4cYulH7SjvpRuICM3CBcRmfKfp
                #               [7]  = 10.100.154.233 (ip)
                #               [8]  = 8500 (port)
                # split('_') -> [-1] = ZrdSgl4cYulH7SjvpRuICM3CBcRmfKfp (node_id)
                entry_parts = entry.split(';')
                if entry_parts[0] == '=' and entry_parts[2] == 'IPv4':
                    node = AlbaNode(volatile=True)
                    node.ip = entry_parts[7]
                    node.port = int(entry_parts[8])
                    node.type = 'ASD'
                    node.node_id = entry_parts[3].split('_')[-1]
                    storagerouter = StorageRouterList.get_by_ip(node.ip)
                    if storagerouter is not None:
                        # Its a public ip from one of the StorageRouters, so that one's preferred
                        nodes[node.node_id] = node
                        continue
                    if node.node_id not in nodes:
                        # Still not in there. If the ip is reachable, this one is choosen
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(1)
                        try:
                            sock.connect((node.ip, node.port))
                            sock.close()
                            nodes[node.node_id] = node
                        except Exception:
                            pass
            return [node.export() for node in nodes.values()]
        except Exception as ex:
            logger.exception('Error discovering Alba nodes: {0}'.format(ex))
            return []

    @staticmethod
    @celery.task(name='albanode.register')
    def register(node_id, ip, port, username, password, asd_ips):
        """
        Adds a Node with a given node_id to the model
        """
        node = AlbaNodeList.get_albanode_by_node_id(node_id)
        if node is None:
            node = AlbaNode()
            node.ip = ip
            node.port = port
            node.username = username
            node.password = password
        data = node.client.get_metadata()
        if data['_success'] is False and data['_error'] == 'Invalid credentials':
            raise RuntimeError('Invalid credentials')
        if data['node_id'] != node_id:
            logger.error('Unexpected node_id: {0} vs {1}'.format(data['node_id'], node_id))
            raise RuntimeError('Unexpected node identifier')
        node.client.set_ips(asd_ips)
        node.node_id = node_id
        node.type = 'ASD'
        node.save()

    @staticmethod
    @celery.task(name='albanode.initialize_disk')
    def initialize_disks(node_guid, disks):
        """
        Initializes a disk
        """
        node = AlbaNode(node_guid)
        available_disks = dict((disk['name'], disk) for disk in node.all_disks)
        failures = {}
        added_disks = []
        for disk in disks:
            logger.debug('Initializing disk {0} at node {1}'.format(disk, node.ip))
            if disk not in available_disks or available_disks[disk]['available'] is False:
                logger.exception('Disk {0} not available on node {1}'.format(disk, node.ip))
                failures[disk] = 'Disk unavailable'
            else:
                result = node.client.add_disk(disk)
                if result['_success'] is False:
                    failures[disk] = result['_error']
                else:
                    added_disks.append(result)
        if node.storagerouter is not None:
            DiskController.sync_with_reality(node.storagerouter_guid)
            for disk in node.storagerouter.disks:
                if disk.path in [result['device'] for result in added_disks]:
                    partition = disk.partitions[0]
                    partition.roles.append(DiskPartition.ROLES.BACKEND)
                    partition.save()
        return failures

    @staticmethod
    @celery.task(name='albanode.remove_disk')
    def remove_disk(alba_backend_guid, node_guid, disk, expected_safety):
        """
        Removes a disk
        """
        node = AlbaNode(node_guid)
        alba_backend = AlbaBackend(alba_backend_guid)
        logger.debug('Removing disk {0} at node {1}'.format(disk, node.ip))
        nodedown = False
        try:
            disks = node.client.get_disks(as_list=False, reraise=True)
        except requests.ConnectionError:
            logger.warning('Alba HTTP Client connection failed on node {0} for disk {1}'.format(node.ip, disk))
            nodedown = True
            # convert to dict
            _disks = node.all_disks
            disks = {}
            for _disk in _disks:
                disks[_disk['name']] = _disk

        if disk not in disks:
            logger.exception('Disk {0} not available for removal on node {1}'.format(disk, node.ip))
            raise RuntimeError('Could not find disk')
        elif disks[disk]['available'] is True or (disks[disk]['available'] is False and nodedown is False):
            final_safety = AlbaController.calculate_safety(alba_backend_guid, [disks[disk]['asd_id']])
            if (final_safety['critical'] != 0 or final_safety['lost'] != 0) and (final_safety['critical'] != expected_safety['critical'] or final_safety['lost'] != expected_safety['lost']):
                raise RuntimeError('Cannot remove disk {0} as the current safety is not as expected ({1} vs {2})'.format(
                    disk, final_safety, expected_safety
                ))
            AlbaController.remove_units(alba_backend_guid, [disks[disk]['asd_id']], absorb_exception=True)
            result = node.client.remove_disk(disk)
            if result['_success'] is False:
                raise RuntimeError('Error removing disk: {0}'.format(result['_error']))
            AlbaController.remove_units(alba_backend_guid, [disks[disk]['asd_id']], absorb_exception=True)
        elif disks[disk]['available'] is False and nodedown is True:
            # Forcefully remove disk -> decommission-osd
            # no safety checks, don't call HTTP client
            logger.warning('Alba decommission osd {0}'.format(disks[disk]['asd_id']))
            AlbaController.remove_units(alba_backend_guid, [disks[disk]['asd_id']], absorb_exception=True)
        else:
            raise RuntimeError("Cannot remove disk {0}, available {1}, nodedown {2}".format(disk, disks[disk]['available'], nodedown))

        asds = [asd for asd in alba_backend.asds if asd.asd_id == disks[disk]['asd_id']]
        asd = asds[0] if len(asds) == 1 else None
        if asd is not None:
            asd.delete()
        node.invalidate_dynamics()
        alba_backend.invalidate_dynamics()
        alba_backend.backend.invalidate_dynamics()
        if node.storagerouter is not None:
            # Run async, deduped, in case it is called multiple times 
            DiskController.async_sync_with_reality(node.storagerouter_guid)
        return True

    @staticmethod
    @celery.task(name='albabide.restart_disk')
    def restart_disk(node_guid, disk):
        """
        Restarts a disk
        """
        node = AlbaNode(node_guid)
        logger.debug('Restarting disk {0} at node {1}'.format(disk, node.ip))
        disks = node.client.get_disks(as_list=False)
        if disk not in disks:
            logger.exception('Disk {0} not available for restart on node {1}'.format(disk, node.ip))
            raise RuntimeError('Could not find disk')
        result = node.client.restart_disk(disk)
        if result['_success'] is False:
            raise RuntimeError('Error restarting disk: {0}'.format(result['_error']))
        alba_backends = []
        for asd in node.asds:
            if asd.alba_backend not in alba_backends:
                alba_backends.append(asd.alba_backend)
        for backend in alba_backends:
            backend.invalidate_dynamics()
        return True

    @staticmethod
    @add_hooks('setup', ['firstnode', 'extranode'])
    @add_hooks('plugin', ['postinstall'])
    def model_local_albanode(**kwargs):
        config_path = '/opt/alba-asdmanager/config/config.json'
        if 'cluster_ip' in kwargs:
            node_ip = kwargs['cluster_ip']
        elif 'ip' in kwargs:
            node_ip = kwargs['ip']
        else:
            raise RuntimeError('The model_local_albanode needs a cluster_ip or ip keyword argument')
        storagerouter = StorageRouterList.get_by_ip(node_ip)
        client = SSHClient(node_ip)
        if client.file_exists(config_path):
            config = json.loads(client.file_read(config_path))
            node = AlbaNodeList.get_albanode_by_ip(node_ip)
            if node is None:
                node = AlbaNode()
            node.storagerouter = storagerouter
            node.ip = node_ip
            node.port = 8500
            node.username = config['main']['username']
            node.password = config['main']['password']
            node.node_id = config['main']['node_id']
            node.type = 'ASD'
            node.save()
