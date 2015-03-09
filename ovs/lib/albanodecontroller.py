# Copyright 2015 CloudFounders NV
# All rights reserved

"""
AlbaNodeController module
"""

import json
import base64
import socket
import requests
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
            discover_result = check_output('avahi-browse -rtp _asd_node._tcp 2> /dev/null | grep asd_node || true', shell=True)
            # logger.debug('Avahi discovery result:\n{0}'.format(discover_result))
            for entry in discover_result.split('\n'):
                # =;eth1;IPv4;asd_node_ZrdSgl4cYulH7SjvpRuICM3CBcRmfKfp;_asd_node._tcp;local;ovs154233.local;10.100.154.233;8500;
                # split(';') -> [3]  = asd_node_ZrdSgl4cYulH7SjvpRuICM3CBcRmfKfp
                #               [7]  = 10.100.154.233 (ip)
                #               [8]  = 8500 (port)
                # split('_') -> [-1] = ZrdSgl4cYulH7SjvpRuICM3CBcRmfKfp (box_id)
                entry_parts = entry.split(';')
                if entry_parts[0] == '=' and entry_parts[2] == 'IPv4':
                    node = AlbaNode()
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
        disks = requests.get('https://{0}:{1}/disks'.format(node.ip, node.port),
                             headers={'Authorization': 'Basic {0}'.format(base64.b64encode('{0}:{1}'.format(node.username, node.password)).strip())},
                             verify=False).json()
        for disk in disks.keys():
            if disk.startswith('_'):
                del disks[disk]
                continue
            for key in disks[disk].keys():
                if key.startswith('_'):
                    del disks[disk][key]
        return disks

    @staticmethod
    @celery.task(name='albanode.register')
    def register(box_id, ip, port, username, password):
        """
        Adds a Node with a given box_id to the model
        """
        node = AlbaNodeList.get_albanode_by_box_id(box_id)
        if node is None:
            node = AlbaNode()
        data = requests.get('https://{0}:{1}/'.format(ip, port),
                            headers={'Authorization': 'Basic {0}'.format(base64.b64encode('{0}:{1}'.format(username, password)).strip())},
                            verify=False).json()
        if data['_success'] is False and data['_error'] == 'Invalid credentials':
            raise RuntimeError('Invalid credentials')
        if data['box_id'] != box_id:
            raise RuntimeError('Unexpected box_id: {0} vs {1}'.format(data['box_id'], box_id))
        node.ip = ip
        node.port = port
        node.username = username
        node.password = password
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
        available_disks = requests.get('https://{0}:{1}/disks'.format(node.ip, node.port),
                                       headers={'Authorization': 'Basic {0}'.format(base64.b64encode('{0}:{1}'.format(node.username, node.password)).strip())},
                                       verify=False).json()
        failures = []
        for disk in disks:
            logger.debug('Initializing disk {0} at node {1}'.format(disk, node.ip))
            if disk not in available_disks or available_disks[disk]['available'] is False:
                logger.exception('Disk {0} not available on node {1}'.format(disk, node.ip))
                failures.append(disk)
            else:
                result = requests.post('https://{0}:{1}/disks/{2}/add'.format(node.ip, node.port, disk),
                                       headers={'Authorization': 'Basic {0}'.format(base64.b64encode('{0}:{1}'.format(node.username, node.password)).strip())},
                                       verify=False).json()
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
        logger.debug('Removing disk {0} at node {1}'.format(disk, node.ip))
        disks = requests.get('https://{0}:{1}/disks'.format(node.ip, node.port),
                             headers={'Authorization': 'Basic {0}'.format(base64.b64encode('{0}:{1}'.format(node.username, node.password)).strip())},
                             verify=False).json()
        if disk not in disks or disks[disk]['available'] is True:
            logger.exception('Disk {0} not available for removal on node {1}'.format(disk, node.ip))
            raise RuntimeError('Could not find disk')
        AlbaController.remove_units(alba_backend_guid, [disks[disk]['asd_id']])
        result = requests.post('https://{0}:{1}/disks/{2}/delete'.format(node.ip, node.port, disk),
                              headers={'Authorization': 'Basic {0}'.format(base64.b64encode('{0}:{1}'.format(node.username, node.password)).strip())},
                              verify=False).json()
        if result['_success'] is True:
            return True
        raise RuntimeError('Error removing disk: {0}'.format(result['_error']))

    @staticmethod
    @setup_hook(['firstnode', 'extranode'])
    def model_local_albanode(**kwargs):
        config_path = '/opt/alba-asdmanager/config/config.json'
        node_ip = kwargs['cluster_ip']
        client = SSHClient.load(node_ip)
        if client.file_exists(config_path):
            config = json.loads(client.file_read(config_path))
            node = AlbaNodeList.get_albanode_by_ip(node_ip)
            if node is None:
                node = AlbaNode()
            node.ip = node_ip
            node.port = 8500
            node.username = config['main']['username']
            node.password = config['main']['password']
            node.box_id = config['main']['box_id']
            node.type = 'ASD'
            node.save()
