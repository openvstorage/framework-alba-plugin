# Copyright 2015 CloudFounders NV
# All rights reserved

"""
AlbaNodeController module
"""

import json
import socket
from subprocess import check_output
from ovs.celery_run import celery
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs.log.logHandler import LogHandler
from ovs.lib.albacontroller import AlbaController
from ovs.lib.helpers.decorators import setup_hook
from ovs.extensions.generic.sshclient import SSHClient

logger = LogHandler('lib', name='albanode')


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
                # split('_') -> [-1] = ZrdSgl4cYulH7SjvpRuICM3CBcRmfKfp (box_id)
                entry_parts = entry.split(';')
                if entry_parts[0] == '=' and entry_parts[2] == 'IPv4':
                    node = AlbaNode(volatile=True)
                    node.ip = entry_parts[7]
                    node.port = int(entry_parts[8])
                    node.type = 'ASD'
                    node.box_id = entry_parts[3].split('_')[-1]
                    storagerouter = StorageRouterList.get_by_ip(node.ip)
                    if storagerouter is not None:
                        # Its a public ip from one of the StorageRouters, so that one's preferred
                        nodes[node.box_id] = node
                        continue
                    if node.box_id not in nodes:
                        # Still not in there. If the ip is reachable, this one is choosen
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(1)
                        try:
                            sock.connect((node.ip, node.port))
                            sock.close()
                            nodes[node.box_id] = node
                        except Exception:
                            pass
            return [node.export() for node in nodes.values()]
        except Exception as ex:
            logger.exception('Error discovering Alba nodes: {0}'.format(ex))
            return []

    @staticmethod
    @celery.task(name='albanode.fetch_disks')
    def fetch_disks(node_guid):
        """
        Return a node's disk information
        """
        node = AlbaNode(node_guid)
        try:
            return dict((disk['name'], disk) for disk in node.all_disks)
        except:
            return {}

    @staticmethod
    @celery.task(name='albanode.fetch_ips')
    def fetch_ips(node_guid=None, ip=None, port=None):
        """
        Returns a list of all available ips on the node
        """
        if node_guid is not None:
            node = AlbaNode(node_guid)
        else:
            node = AlbaNode()
            node.ip = ip
            node.port = port
        return node.ips

    @staticmethod
    @celery.task(name='albanode.register')
    def register(box_id, ip, port, username, password, asd_ips):
        """
        Adds a Node with a given box_id to the model
        """
        node = AlbaNodeList.get_albanode_by_box_id(box_id)
        if node is None:
            node = AlbaNode()
            node.ip = ip
            node.port = port
            node.username = username
            node.password = password
        data = node.client.get_metadata()
        if data['_success'] is False and data['_error'] == 'Invalid credentials':
            raise RuntimeError('Invalid credentials')
        if data['box_id'] != box_id:
            raise RuntimeError('Unexpected box_id: {0} vs {1}'.format(data['box_id'], box_id))
        node.client.set_ips(asd_ips)
        node.box_id = box_id
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
        failures = []
        for disk in disks:
            logger.debug('Initializing disk {0} at node {1}'.format(disk, node.ip))
            if disk not in available_disks or available_disks[disk]['available'] is False:
                logger.exception('Disk {0} not available on node {1}'.format(disk, node.ip))
                failures.append(disk)
            else:
                result = node.client.add_disk(disk)
                if result['_success'] is False:
                    failures.append(disk)
        return failures

    @staticmethod
    @celery.task(name='albanode.remove_disk')
    def remove_disk(alba_backend_guid, node_guid, disk):
        """
        Removes a disk
        """
        node = AlbaNode(node_guid)
        alba_backend = AlbaBackend(alba_backend_guid)
        logger.debug('Removing disk {0} at node {1}'.format(disk, node.ip))
        disks = node.client.get_disks(as_list=False)
        if disk not in disks or disks[disk]['available'] is True:
            logger.exception('Disk {0} not available for removal on node {1}'.format(disk, node.ip))
            raise RuntimeError('Could not find disk')
        asds = [asd for asd in alba_backend.asds if asd.asd_id == disks[disk]['asd_id']]
        asd = asds[0] if len(asds) == 1 else None
        AlbaController.remove_units(alba_backend_guid, [disks[disk]['asd_id']], absorb_exception=True)
        result = node.client.remove_disk(disk)
        if result['_success'] is False:
            raise RuntimeError('Error removing disk: {0}'.format(result['_error']))
        AlbaController.remove_units(alba_backend_guid, [disks[disk]['asd_id']], absorb_exception=True)
        if asd is not None:
            asd.delete()
        alba_backend.invalidate_dynamics()
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
        if disk not in disks or disks[disk]['available'] is True or disks[disk]['state']['state'] != 'error':
            logger.exception('Disk {0} not available for restart on node {1}'.format(disk, node.ip))
            raise RuntimeError('Could not find disk')
        result = node.client.restart_disk(disk)
        if result['_success'] is False:
            raise RuntimeError('Error restarting disk: {0}'.format(result['_error']))
        return True

    @staticmethod
    @setup_hook(['firstnode', 'extranode'])
    def model_local_albanode(**kwargs):
        config_path = '/opt/alba-asdmanager/config/config.json'
        node_ip = kwargs['cluster_ip']
        storagerouter = StorageRouterList.get_by_ip(node_ip)
        client = SSHClient.load(node_ip)
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
            node.box_id = config['main']['box_id']
            node.type = 'ASD'
            node.save()
