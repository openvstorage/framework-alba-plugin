# Copyright (C) 2016 iNuron NV
#
# This file is part of Open vStorage Open Source Edition (OSE),
# as available from
#
#      http://www.openvstorage.org and
#      http://www.openvstorage.com.
#
# This file is free software; you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License v3 (GNU AGPLv3)
# as published by the Free Software Foundation, in version 3 as it comes
# in the LICENSE.txt file of the Open vStorage OSE distribution.
#
# Open vStorage is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY of any kind.

"""
AlbaNodeController module
"""

import random
import requests
import string
import sys
from ovs.celery_run import celery
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.hybrids.albadisk import AlbaDisk
from ovs.dal.hybrids.diskpartition import DiskPartition
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs.extensions.db.etcd.configuration import EtcdConfiguration
from ovs.log.log_handler import LogHandler
from ovs.lib.albacontroller import AlbaController
from ovs.lib.disk import DiskController
from ovs.lib.helpers.decorators import add_hooks
from ovs.lib.helpers.decorators import ensure_single


class AlbaNodeController(object):
    """
    Contains all BLL related to ALBA nodes
    """
    NR_OF_AGENTS_ETCD_TEMPLATE = '/ovs/alba/backends/{0}/maintenance/nr_of_agents'
    _logger = LogHandler.get('lib', name='albanode')
    ASD_CONFIG_DIR = '/ovs/alba/asds/{0}'
    ASD_CONFIG = '{0}/config'.format(ASD_CONFIG_DIR)

    @staticmethod
    @celery.task(name='albanode.register')
    def register(node_id):
        """
        Adds a Node with a given node_id to the model
        :param node_id: ID of the ALBA node
        :type node_id: str

        :return: None
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
            AlbaNodeController._logger.error('Unexpected node_id: {0} vs {1}'.format(data['node_id'], node_id))
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
        :type node_guid: str

        :param disks: Disks to initialize
        :type disks: dict

        :return: Dict of all failures with as key the Diskname, and as value the error
        :rtype: dict
        """
        node = AlbaNode(node_guid)
        try:
            available_disks = node.client.get_disks()
        except (requests.ConnectionError, requests.Timeout):
            AlbaNodeController._logger.exception('Could not connect to node {0} to validate disks'.format(node.guid))
            raise
        failures = {}
        added_disks = []
        for disk_id, amount in disks.iteritems():
            AlbaNodeController._logger.debug('Initializing disk {0} at node {1}'.format(disk_id, node.ip))
            if disk_id not in available_disks or available_disks[disk_id]['available'] is False:
                AlbaNodeController._logger.exception('Disk {0} not available on node {1}'.format(disk_id, node.ip))
                failures[disk_id] = 'Disk unavailable'
            else:
                disk = AlbaDisk()
                disk.name = disk_id
                disk.alba_node = node
                disk.save()
                result = node.client.add_disk(disk_id)
                if result['_success'] is False:
                    failures[disk_id] = result['_error']
                    disk.delete()
                else:
                    device = result['device']
                    for _ in xrange(amount):
                        result = node.client.add_asd(disk_id)
                        if result['_success'] is False:
                            failures[disk_id] = result['_error']
                    added_disks.append(device)
        if node.storagerouter is not None:
            DiskController.sync_with_reality(node.storagerouter_guid)
            for disk in node.storagerouter.disks:
                if disk.path in added_disks:
                    partition = disk.partitions[0]
                    partition.roles.append(DiskPartition.ROLES.BACKEND)
                    partition.save()
        return failures

    @staticmethod
    @celery.task(name='albanode.remove_disk')
    @ensure_single(task_name='albanode.remove_disk', mode='CHAINED')
    def remove_disk(node_guid, disk):
        """
        Removes a disk
        :param node_guid: Guid of the node to remove a disk from
        :type node_guid: str

        :param disk: Disk name to remove
        :type disk: str

        :return: None
        """
        node = AlbaNode(node_guid)
        offline_node = False
        try:
            if disk not in node.client.get_disks():
                raise RuntimeError('Disk {0} not available on node {1}'.format(disk, node.guid))
        except (requests.ConnectionError, requests.Timeout):
            AlbaNodeController._logger.warning('Could not connect to node {0} to validate disks'.format(node.guid))
            offline_node = True
        node_id = node.node_id
        asds = {}
        for backend in AlbaBackendList.get_albabackends():
            storage_stack = backend.storage_stack
            if node_id in storage_stack and disk in storage_stack[node_id]:
                asds.update(storage_stack[node_id][disk]['asds'])
        for asd_info in asds.values():
            if (offline_node is False and asd_info['status'] != 'available') or (offline_node is True and asd_info['status_detail'] == 'nodedown'):
                AlbaNodeController._logger.error('Disk {0} has still non-available ASDs on node {1}'.format(disk, node.ip))
                raise RuntimeError('Disk {0} has still some non-available ASDs'.format(disk))
        if offline_node is False:
            result = node.client.remove_disk(disk)
            if result['_success'] is False:
                raise RuntimeError('Error removing disk {0}: {1}'.format(disk, result['_error']))
        for model_disk in node.disks:
            if model_disk.name == disk:
                for asd in model_disk.asds:
                    asd.delete()
                model_disk.delete()
        node.invalidate_dynamics()
        if node.storagerouter is not None:
            DiskController.sync_with_reality(node.storagerouter_guid)

    @staticmethod
    @celery.task(name='albanode.remove_asd')
    @ensure_single(task_name='albanode.remove_asd', mode='CHAINED')
    def remove_asd(node_guid, asd_id, expected_safety):
        """
        Removes an ASD

        :param node_guid: Guid of the node to remove a disk from
        :type node_guid: str

        :param asd_id: ASD to remove
        :type asd_id: str

        :param expected_safety: Expected safety after having removed the disk
        :type expected_safety: dict

        :return: True
        :rtype: bool
        """
        node = AlbaNode(node_guid)
        AlbaNodeController._logger.debug('Removing ASD {0} at node {1}'.format(asd_id, node.ip))
        model_asd = None
        for disk in node.disks:
            for asd in disk.asds:
                if asd.asd_id == asd_id:
                    model_asd = asd
                    break
            if model_asd is not None:
                break
        if model_asd is None:
            raise RuntimeError('Could not locate asd {0} in the model'.format(asd_id))
        alba_backend = model_asd.alba_backend

        asds = {}
        try:
            asds = node.client.get_asds()
        except (requests.ConnectionError, requests.Timeout):
            AlbaNodeController._logger.warning('Could not connect to node {0} to validate asd'.format(node.guid))
        disk_id = None
        for _disk_id in asds:
            if asd_id in asds[_disk_id]:
                disk_id = _disk_id
                break

        AlbaController.remove_units(alba_backend.guid, [asd_id], absorb_exception=True)
        if disk_id is not None:
            final_safety = AlbaController.calculate_safety(alba_backend.guid, [asd_id])
            safety_lost = final_safety['lost']
            safety_crit = final_safety['critical']
            if (safety_crit != 0 or safety_lost != 0) and (safety_crit != expected_safety['critical'] or safety_lost != expected_safety['lost']):
                raise RuntimeError('Cannot remove ASD {0} as the current safety is not as expected ({1} vs {2})'.format(asd_id, final_safety, expected_safety))

            result = node.client.delete_asd(disk_id, asd_id)
            if result['_success'] is False:
                raise RuntimeError('Error removing ASD: {0}'.format(result['_error']))
        else:
            AlbaNodeController._logger.warning('Alba decommission osd {0} without safety validations (node down)'.format(asd_id))
        if EtcdConfiguration.exists(AlbaNodeController.ASD_CONFIG.format(asd_id), raw=True):
            EtcdConfiguration.delete(AlbaNodeController.ASD_CONFIG_DIR.format(asd_id), raw=True)

        model_asd.delete()
        alba_backend.invalidate_dynamics()
        alba_backend.backend.invalidate_dynamics()
        if node.storagerouter is not None:
            DiskController.sync_with_reality(node.storagerouter_guid)

        return disk_id

    @staticmethod
    @celery.task(name='albanode.reset_asd')
    def reset_asd(node_guid, asd_id, expected_safety):
        """
        Removes and readds an ASD to a Disk

        :param node_guid: Guid of the node to remove a disk from
        :type node_guid: str

        :param asd_id: ASD to remove
        :type asd_id: str

        :param expected_safety: Expected safety after having removed the disk
        :type expected_safety: dict

        :return: None
        """
        node = AlbaNode(node_guid)
        disk_id = AlbaNodeController.remove_asd(node_guid, asd_id, expected_safety)
        try:
            result = node.client.add_asd(disk_id)
            if result['_success'] is False:
                AlbaNodeController._logger.error('Error resetting ASD: {0}'.format(result['_error']))
                raise RuntimeError(result['_error'])
        except (requests.ConnectionError, requests.Timeout):
            AlbaNodeController._logger.warning('Could not connect to node {0} to (re)configure ASD'.format(node.guid))

    @staticmethod
    @celery.task(name='albanode.restart_asd')
    def restart_asd(node_guid, asd_id):
        """
        Restarts an ASD on a given Node
        :param node_guid: Guid of the node to remove a disk from
        :type node_guid: str

        :param asd_id: ASD to remove
        :type asd_id: str

        :return: None
        """
        node = AlbaNode(node_guid)
        try:
            asds = node.client.get_asds()
        except (requests.ConnectionError, requests.Timeout):
            AlbaNodeController._logger.warning('Could not connect to node {0} to validate asd'.format(node.guid))
            raise

        disk_id = None
        for _disk_id in asds:
            if asd_id in asds[_disk_id]:
                disk_id = _disk_id
                break
        if disk_id is None:
            AlbaNodeController._logger.error('Could not locate ASD {0} on node {1}'.format(asd_id, node_guid))
            raise RuntimeError('Could not locate ASD {0} on node {1}'.format(asd_id, node_guid))

        result = node.client.restart_asd(disk_id, asd_id)
        if result['_success'] is False:
            AlbaNodeController._logger.error('Error restarting ASD: {0}'.format(result['_error']))
            raise RuntimeError(result['_error'])

    @staticmethod
    @celery.task(name='albanode.restart_disk')
    def restart_disk(node_guid, disk):
        """
        Restarts a disk
        :param node_guid: Guid of the node to restart a disk of
        :type node_guid: str

        :param disk: Disk name to be restarted
        :type disk: str

        :return: None
        """
        node = AlbaNode(node_guid)
        AlbaNodeController._logger.debug('Restarting disk {0} at node {1}'.format(disk, node.ip))
        try:
            disks = node.client.get_disks()
            if disk not in disks:
                AlbaNodeController._logger.exception('Disk {0} not available for restart on node {1}'.format(disk, node.ip))
                raise RuntimeError('Could not find disk')
        except (requests.ConnectionError, requests.Timeout):
            AlbaNodeController._logger.warning('Could not connect to node {0} to validate disk'.format(node.guid))
            raise

        result = node.client.restart_disk(disk)
        if result['_success'] is False:
            raise RuntimeError('Error restarting disk: {0}'.format(result['_error']))
        for backend in AlbaBackendList.get_albabackends():
            backend.invalidate_dynamics()

    @staticmethod
    @add_hooks('setup', ['firstnode', 'extranode'])
    @add_hooks('plugin', ['postinstall'])
    def model_local_albanode(**kwargs):
        """
        Add all ALBA nodes known to etcd to the model
        :param kwargs: Kwargs containing information regarding the node
        :type kwargs: dict

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
        service_template_key = 'alba-maintenance_{0}-{1}'
        maintenance_agents_map = {}
        asd_nodes = AlbaNodeList.get_albanodes()
        nr_of_storage_nodes = len(asd_nodes)

        def _get_node_load(backend_name):
            highest_load = 0
            lowest_load = sys.maxint
            agent_load = {'high_load_node': asd_nodes[0] if asd_nodes else None,
                          'low_load_node': asd_nodes[0] if asd_nodes else None,
                          'total_load': 0}
            for asd_node in asd_nodes:
                actual_nr_of_agents = 0
                maint_services = asd_node.client.list_maintenance_services()
                for service_name in maint_services:
                    if service_template_key.format(backend_name, '') in service_name:
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
                                            'actual': _get_node_load(name)['total_load'],
                                            'backend': alba_backend.backend}

        for name, values in maintenance_agents_map.iteritems():
            AlbaNodeController._logger.info('Checking backend: {0}'.format(name))
            to_process = values['required'] - values['actual']

            if to_process == 0:
                AlbaNodeController._logger.info('No action required for: {0}'.format(name))
            elif to_process >= 0:
                AlbaNodeController._logger.info('Adding {0} maintenance agent(s) for {1}'.format(to_process, name))
                for _ in xrange(to_process):
                    unique_hash = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(16))
                    node = _get_node_load(name)['low_load_node']
                    AlbaNodeController._logger.info('Service to add: ' + service_template_key.format(name, unique_hash))
                    if node and node.client:
                        node.client.add_maintenance_service(service_template_key.format(name, unique_hash),
                                                            values['backend'].alba_backend.guid,
                                                            AlbaController.get_abm_service_name(values['backend']))
                        AlbaNodeController._logger.info('Service added')
            else:
                to_process = abs(to_process)
                AlbaNodeController._logger.info('Removing {0} maintenance agent(s) for {1}'.format(to_process, name))
                for _ in xrange(to_process):
                    node = _get_node_load(name)['high_load_node']
                    services = node.client.list_maintenance_services()
                    if services and node and node.client:
                        for service in services:
                            if 'alba-maintenance_' + name in service:
                                node.client.remove_maintenance_service(service)
                                break
