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

import requests
from ovs.celery_run import celery
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.diskpartition import DiskPartition
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs.extensions.db.etcd.configuration import EtcdConfiguration
from ovs.log.logHandler import LogHandler
from ovs.lib.albacontroller import AlbaController
from ovs.lib.disk import DiskController
from ovs.lib.helpers.decorators import add_hooks

logger = LogHandler.get('lib', name='albanode')


class AlbaNodeController(object):
    """
    Contains all BLL related to ALBA nodes
    """
    @staticmethod
    @celery.task(name='albanode.register')
    def register(node_id):
        """
        Adds a Node with a given node_id to the model
        :param node_id: ID of the ALBA node
        """
        node = AlbaNodeList.get_albanode_by_node_id(node_id)
        network_config = EtcdConfiguration.get('/ovs/alba/asdnodes/{0}/config/network'.format(node_id))
        if node is None:
            main_config = EtcdConfiguration.get('/ovs/alba/asdnodes/{0}/config/main'.format(node_id))
            node = AlbaNode()
            node.ip = main_config['ip']
            node.port = network_config['port']
            node.username = main_config['username']
            node.password = main_config['password']
        data = node.client.get_metadata()
        if data['_success'] is False and data['_error'] == 'Invalid credentials':
            raise RuntimeError('Invalid credentials')
        if data['node_id'] != node_id:
            logger.error('Unexpected node_id: {0} vs {1}'.format(data['node_id'], node_id))
            raise RuntimeError('Unexpected node identifier')
        node.node_id = node_id
        node.type = 'ASD'
        node.save()

    @staticmethod
    @celery.task(name='albanode.initialize_disk')
    def initialize_disks(node_guid, disks):
        """
        Initializes a disk
        :param node_guid: Guid of the node which disks need to be initialized
        :param disks: Disks to initialize
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
        :param alba_backend_guid: Guid of the ALBA backend
        :param node_guid: Guid of the node to remove a disk from
        :param disk: Disk to remove
        :param expected_safety: Expected safety after having removed the disk
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

        if disks[disk]['available'] is True or (disks[disk]['available'] is False and nodedown is False):
            final_safety = AlbaController.calculate_safety(alba_backend_guid, [disks[disk]['asd_id']])
            if (final_safety['critical'] != 0 or final_safety['lost'] != 0) and (final_safety['critical'] != expected_safety['critical'] or final_safety['lost'] != expected_safety['lost']):
                raise RuntimeError('Cannot remove disk {0} as the current safety is not as expected ({1} vs {2})'.format(disk, final_safety, expected_safety))

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
            raise RuntimeError("Cannot remove disk {0}, available {1}, node down {2}".format(disk, disks[disk]['available'], nodedown))

        asds = [asd for asd in alba_backend.asds if asd.asd_id == disks[disk]['asd_id']]
        asd = asds[0] if len(asds) == 1 else None
        if asd is not None:
            asd.delete()
        node.invalidate_dynamics()
        alba_backend.invalidate_dynamics()
        alba_backend.backend.invalidate_dynamics()
        if node.storagerouter is not None:
            DiskController.sync_with_reality(node.storagerouter_guid)
        return True

    @staticmethod
    @celery.task(name='albanode.restart_disk')
    def restart_disk(node_guid, disk):
        """
        Restarts a disk
        :param node_guid: Guid of the node to restart a disk of
        :param disk: Disk to be restarted
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
        """
        Add all ALBA nodes known to etcd to the model
        :param kwargs: Kwargs containing information regarding the node
        :return: None
        """
        if 'cluster_ip' in kwargs:
            node_ip = kwargs['cluster_ip']
        elif 'ip' in kwargs:
            node_ip = kwargs['ip']
        else:
            raise RuntimeError('The model_local_albanode needs a cluster_ip or ip keyword argument')
        storagerouter = StorageRouterList.get_by_ip(node_ip)

        if EtcdConfiguration.dir_exists('/ovs/alba/asdnodes'):
            for node_id in EtcdConfiguration.list('/ovs/alba/asdnodes'):
                node = AlbaNodeList.get_albanode_by_ip(node_ip)
                if node is None:
                    node = AlbaNode()
                node.storagerouter = storagerouter
                node.ip = node_ip
                node.port = 8500
                node.username = EtcdConfiguration.get('/ovs/alba/asdnodes/{0}/config/main|username'.format(node_id))
                node.password = EtcdConfiguration.get('/ovs/alba/asdnodes/{0}/config/main|password'.format(node_id))
                node.node_id = node_id
                node.type = 'ASD'
                node.save()
