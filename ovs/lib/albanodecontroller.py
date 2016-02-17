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

import random
import requests
import string
from ovs.celery_run import celery
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.diskpartition import DiskPartition
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs.extensions.db.etcd.configuration import EtcdConfiguration
from ovs.log.logHandler import LogHandler
from ovs.lib.albacontroller import AlbaController
from ovs.lib.disk import DiskController
from ovs.lib.helpers.decorators import add_hooks
from ovs.lib.helpers.decorators import ensure_single

logger = LogHandler.get('lib', name='albanode')


class AlbaNodeController(object):
    """
    Contains all BLL related to ALBA nodes
    """

    NR_OF_AGENTS_ETCD_TEMPLATE = '/ovs/alba/backends/{0}/maintenance/nr_of_agents'

    @staticmethod
    @celery.task(name='albanode.register')
    def register(node_id):
        """
        Adds a Node with a given node_id to the model
        :param node_id: ID of the ALBA node
        """
        node = AlbaNodeList.get_albanode_by_node_id(node_id)
        if node is None:
            main_config = EtcdConfiguration.get('/ovs/alba/asdnodes/{0}/config/main'.format(node_id))
            node = AlbaNode()
            node.ip = main_config['ip']
            node.port = main_config['port']
            node.username = main_config['username']
            node.password = main_config['password']
            node.storagerouter = StorageRouterList.get_by_ip(main_config['ip'])
        data = node.client.get_metadata()
        if data['_success'] is False and data['_error'] == 'Invalid credentials':
            raise RuntimeError('Invalid credentials')
        if data['node_id'] != node_id:
            logger.error('Unexpected node_id: {0} vs {1}'.format(data['node_id'], node_id))
            raise RuntimeError('Unexpected node identifier')
        node.node_id = node_id
        node.type = 'ASD'
        node.save()

        # increase maintenance agents count for all nodes by 1
        for backend in AlbaBackendList.get_albabackends():
            nr_of_agents_key = AlbaNodeController.NR_OF_AGENTS_ETCD_TEMPLATE.format(backend.guid)
            if EtcdConfiguration.exists(nr_of_agents_key):
                EtcdConfiguration.set(nr_of_agents_key, int(EtcdConfiguration.get(nr_of_agents_key) + 1))
            else:
                EtcdConfiguration.set(nr_of_agents_key, 1)
        AlbaNodeController.checkup_maintenance_agents()

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
    @ensure_single(task_name='albanode.remove_disk', mode='CHAINED')
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
        disk_info = None
        try:
            disks = node.client.get_disks(as_list=False, reraise=True)
            disk_info = disks.get(disk)
        except requests.ConnectionError:
            logger.warning('Alba HTTP Client connection failed on node {0} for disk {1}'.format(node.ip, disk))
            nodedown = True
            for d in node.all_disks:
                if d['name'] == disk:
                    disk_info = d
                    break

        if disk_info is None or not isinstance(disk_info, dict):
            logger.exception('Disk {0} not available for removal on node {1}'.format(disk, node.ip))
            raise RuntimeError('Could not find disk with name {0}'.format(disk))

        disk_asd_id = disk_info.get('asd_id')
        disk_available = disk_info.get('available')
        if disk_asd_id is None or disk_available is None:
            raise RuntimeError('Failed to retrieve information about disk with name {0}'.format(disk))

        asds = [asd for asd in alba_backend.asds if asd.asd_id == disk_asd_id]
        if len(asds) > 1:
            raise RuntimeError('Multiple ASDs with ID {0}'.format(disk_asd_id))

        if disk_available is True or nodedown is False:
            final_safety = AlbaController.calculate_safety(alba_backend_guid, [disk_asd_id])
            safety_lost = final_safety['lost']
            safety_crit = final_safety['critical']
            if (safety_crit != 0 or safety_lost != 0) and (safety_crit != expected_safety['critical'] or safety_lost != expected_safety['lost']):
                raise RuntimeError('Cannot remove disk {0} as the current safety is not as expected ({1} vs {2})'.format(disk, final_safety, expected_safety))

            AlbaController.remove_units(alba_backend_guid, [disk_asd_id])
            result = node.client.remove_disk(disk)
            if result['_success'] is False:
                raise RuntimeError('Error removing disk: {0}'.format(result['_error']))
        else:
            # Forcefully remove disk -> decommission-osd
            # no safety checks, don't call HTTP client
            logger.warning('Alba decommission osd {0}'.format(disk_asd_id))
            AlbaController.remove_units(alba_backend_guid, [disk_asd_id], absorb_exception=True)

        if len(asds) == 1:
            asds[0].delete()
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
        _ = kwargs
        if EtcdConfiguration.dir_exists('/ovs/alba/asdnodes'):
            for node_id in EtcdConfiguration.list('/ovs/alba/asdnodes'):
                node = AlbaNodeList.get_albanode_by_node_id(node_id)
                if node is None:
                    node = AlbaNode()
                main_config = EtcdConfiguration.get('/ovs/alba/asdnodes/{0}/config/main'.format(node_id))
                node.type = 'ASD'
                node.node_id = node_id
                node.ip = main_config['ip']
                node.port = main_config['port']
                node.username = main_config['username']
                node.password = main_config['password']
                node.storagerouter = StorageRouterList.get_by_ip(main_config['ip'])
                node.save()

    @staticmethod
    def checkup_maintenance_agents():
        """
        Check if requested nr of maintenance agents / backend is actually present
        Add / remove as necessary
        :return: None
        """
        service_template_key = 'ovs-alba-maintenance_{0}-{1}'
        maintenance_agents_map = {}
        asd_nodes = AlbaNodeList.get_albanodes()
        nr_of_storage_nodes = len(asd_nodes)

        def get_node_load(backend_name):
            highest_load = 0
            lowest_load = 0
            agent_load = {'high_load_node': asd_nodes[0] if asd_nodes else None,
                          'low_load_node': asd_nodes[0] if asd_nodes else None,
                          'total_load': 0}
            for asd_node in asd_nodes:
                actual_nr_of_agents = 0
                services = asd_node.client.list_maintenance_services()['services']
                if services:
                    for filename in services.keys():
                        if service_template_key.format(backend_name, '') in filename:
                            actual_nr_of_agents += 1
                    if actual_nr_of_agents > highest_load:
                        agent_load['high_load_node'] = asd_node
                        highest_load = actual_nr_of_agents
                    if actual_nr_of_agents < lowest_load:
                        agent_load['low_load_node'] = asd_node
                        lowest_load = actual_nr_of_agents
                    agent_load['total_load'] += actual_nr_of_agents

            return agent_load

        alba_backends = AlbaBackendList.get_albabackends()
        for alba_backend in alba_backends:
            nr_of_agents_key = AlbaNodeController.NR_OF_AGENTS_ETCD_TEMPLATE.format(alba_backend.guid)
            name = alba_backend.backend.name
            if not EtcdConfiguration.exists(nr_of_agents_key):
                EtcdConfiguration.set(nr_of_agents_key, nr_of_storage_nodes)
            required_nr = EtcdConfiguration.get(nr_of_agents_key)
            maintenance_agents_map[name] = {'required': required_nr,
                                            'actual': get_node_load(name)['total_load'],
                                            'alba_backend': alba_backend}

        for name, values in maintenance_agents_map.iteritems():
            logger.info('Checking backend: {0}'.format(name))
            to_process = values['required'] - values['actual']

            if to_process == 0:
                logger.info('No action required for: {0}'.format(name))
            elif to_process >= 0:
                logger.info('Adding {0} maintenance agent(s) for {1}'.format(to_process, name))
                for _ in xrange(to_process):
                    unique_hash = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(32))
                    node = get_node_load(name)['high_load_node']
                    logger.info('Service to add: ' + service_template_key.format(name, unique_hash))
                    if node and node.client:
                        node.client.add_maintenance_service(service_template_key.format(name, unique_hash),
                                                            values['alba_backend'].guid,
                                                            AlbaController._get_abm_service_name(values['alba_backend']))
                        logger.info('Service added')
            else:
                to_process = abs(to_process)
                logger.info('Removing {0} maintenance agent(s) for {1}'.format(to_process, name))
                for _ in xrange(to_process):
                    node = get_node_load(name)['high_load_node']
                    services = node.client.list_maintenance_services()['services'].keys()
                    if services and node and node.client:
                        for service in services:
                            if 'ovs-alba-maintenance_' + name in service:
                                node.client.remove_maintenance_service(service)
                                break
