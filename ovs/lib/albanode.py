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

import requests
from ovs.celery_run import celery
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.hybrids.albadisk import AlbaDisk
from ovs.dal.hybrids.diskpartition import DiskPartition
from ovs.dal.hybrids.storagerouter import StorageRouter
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.disklist import DiskList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs.extensions.generic.configuration import Configuration
from ovs.extensions.generic.sshclient import SSHClient
from ovs.extensions.plugins.asdmanager import InvalidCredentialsError
from ovs.log.log_handler import LogHandler
from ovs.lib.alba import AlbaController
from ovs.lib.disk import DiskController
from ovs.lib.helpers.decorators import add_hooks
from ovs.lib.helpers.decorators import ensure_single


class AlbaNodeController(object):
    """
    Contains all BLL related to ALBA nodes
    """
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
            main_config = Configuration.get('/ovs/alba/asdnodes/{0}/config/main'.format(node_id))
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
        AlbaController.checkup_maintenance_agents.delay()

    @staticmethod
    @celery.task(name='albanode.remove_node')
    def remove_node(node_guid):
        """
        Removes an ALBA node
        :param node_guid: Guid of the ALBA node to remove
        :type node_guid: str
        :return: None
        """
        node = AlbaNode(node_guid)
        for disk in node.disks:
            for osd in disk.osds:
                AlbaNodeController.remove_asd(node_guid=osd.alba_disk.alba_node_guid, asd_id=osd.osd_id, expected_safety=None)
            AlbaNodeController.remove_disk(node_guid=disk.alba_node_guid, device_alias=disk.aliases[0])

        try:
            for service_name in node.client.list_maintenance_services():
                node.client.remove_maintenance_service(service_name)
        except (requests.ConnectionError, requests.Timeout):
            AlbaNodeController._logger.exception('Could not connect to node {0} to retrieve the maintenance services'.format(node.guid))
        except InvalidCredentialsError:
            AlbaNodeController._logger.warning('Failed to retrieve the maintenance services for ALBA node {0}'.format(node.node_id))

        if Configuration.dir_exists('/ovs/alba/asdnodes/{0}'.format(node.node_id)):
            Configuration.delete('/ovs/alba/asdnodes/{0}'.format(node.node_id))

        node.delete()

    @staticmethod
    @celery.task(name='albanode.replace_node')
    def replace_node(old_node_guid, new_node_id):
        """
        Replace an ALBA node
        :param old_node_guid: Guid of the old ALBA node being replaced
        :type old_node_guid: str
        :param new_node_id: ID of the new ALBA node
        :type new_node_id: str
        :return: None
        """
        AlbaNodeController.remove_node(node_guid=old_node_guid)
        AlbaNodeController.register(node_id=new_node_id)

    @staticmethod
    @celery.task(name='albanode.initialize_disk')
    def initialize_disks(node_guid, disks):
        """
        Initializes 1 or multiple disks
        :param node_guid: Guid of the node to which the disks belong
        :type node_guid: str
        :param disks: Disks to initialize  (key: device_alias, value: amount of ASDs to deploy)
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
        for device_alias, amount in disks.iteritems():
            device_id = device_alias.split('/')[-1]
            AlbaNodeController._logger.debug('Initializing disk {0} at node {1}'.format(device_alias, node.ip))
            if device_id not in available_disks or available_disks[device_id]['available'] is False:
                AlbaNodeController._logger.exception('Disk {0} not available on node {1}'.format(device_alias, node.ip))
                failures[device_alias] = 'Disk unavailable'
            else:
                add_disk_result = node.client.add_disk(disk_id=device_id)
                # Verify if an AlbaDisk with found aliases already exists (eg: When initialize individual and initialize all run at the same time)
                exists = False
                aliases = add_disk_result['aliases']
                for alba_disk in node.disks:
                    if set(alba_disk.aliases).intersection(set(aliases)):
                        exists = True
                        break
                if exists is True:
                    continue
                disk = AlbaDisk()
                disk.aliases = aliases
                disk.alba_node = node
                disk.save()
                if add_disk_result['_success'] is False:
                    failures[device_alias] = add_disk_result['_error']
                    disk.delete()
                else:
                    device_id = disk.aliases[0].split('/')[-1]
                    for _ in xrange(amount):
                        add_asd_result = node.client.add_asd(disk_id=device_id)
                        if add_asd_result['_success'] is False:
                            failures[device_alias] = add_asd_result['_error']
                    added_disks.extend(add_disk_result['aliases'])
        if node.storagerouter is not None:
            DiskController.sync_with_reality(storagerouter_guid=node.storagerouter_guid)
            for disk in node.storagerouter.disks:
                if set(disk.aliases).intersection(set(added_disks)):
                    partition = disk.partitions[0]
                    if DiskPartition.ROLES.BACKEND not in partition.roles:
                        partition.roles.append(DiskPartition.ROLES.BACKEND)
                        partition.save()
        return failures

    @staticmethod
    @celery.task(name='albanode.remove_disk')
    @ensure_single(task_name='albanode.remove_disk', mode='CHAINED')
    def remove_disk(node_guid, device_alias):
        """
        Removes a disk
        :param node_guid: Guid of the node to remove a disk from
        :type node_guid: str
        :param device_alias: Alias of the device to remove  (eg: /dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0)
        :type device_alias: str
        :return: None
        """
        asds = {}
        node = AlbaNode(node_guid)
        node_id = node.node_id
        device_id = device_alias.split('/')[-1]
        offline_node = False

        # Verify client connectivity
        try:
            _ = node.client.get_disks()
        except (requests.ConnectionError, requests.Timeout, InvalidCredentialsError):
            AlbaNodeController._logger.warning('Could not connect to node {0} to validate disks'.format(node.guid))
            offline_node = True

        # Retrieve ASD information for the ALBA Disk
        for backend in AlbaBackendList.get_albabackends():
            local_stack = backend.local_stack
            if node_id in local_stack and device_id in local_stack[node_id]:
                asds.update(local_stack[node_id][device_id]['asds'])
        for asd_info in asds.values():
            if (offline_node is False and asd_info.get('status') != 'available') or (offline_node is True and asd_info.get('status_detail') == 'nodedown'):
                AlbaNodeController._logger.error('Disk {0} has still non-available ASDs on node {1}'.format(device_alias, node.ip))
                raise RuntimeError('Disk {0} on ALBA node {1} has still some non-available ASDs'.format(device_alias, node_id))

        # Retrieve the Disk from the framework model matching the ALBA Disk
        disk_to_clear = None
        for disk in DiskList.get_disks():
            if device_alias in disk.aliases:
                disk_to_clear = disk
                break

        # Remove the ALBA Disk making use of the ASD Manager Client
        if offline_node is False:
            result = node.client.remove_disk(disk_id=device_id, partition_aliases=disk_to_clear.partitions[0].aliases if len(disk_to_clear.partitions) > 0 else [])
            if result['_success'] is False:
                raise RuntimeError('Error removing disk {0}: {1}'.format(device_alias, result['_error']))

        # Clean the model
        for model_disk in node.disks:
            if device_alias in model_disk.aliases:
                for osd in model_disk.osds:
                    osd.delete()
                model_disk.delete()
        if disk_to_clear is not None:
            for partition in disk_to_clear.partitions:
                partition.roles = []
                partition.mountpoint = None
                partition.save()
        node.invalidate_dynamics()
        if node.storagerouter is not None:
            DiskController.sync_with_reality(storagerouter_guid=node.storagerouter_guid)

    @staticmethod
    @celery.task(name='albanode.remove_asd')
    @ensure_single(task_name='albanode.remove_asd', mode='CHAINED')
    def remove_asd(node_guid, asd_id, expected_safety):
        """
        Removes an ASD
        :param node_guid: Guid of the node to remove an ASD from
        :type node_guid: str
        :param asd_id: ID of the ASD to remove
        :type asd_id: str
        :param expected_safety: Expected safety after having removed the ASD
        :type expected_safety: dict or None
        :return: Aliases of the disk on which the ASD was removed
        :rtype: list
        """
        node = AlbaNode(node_guid)
        AlbaNodeController._logger.debug('Removing ASD {0} at node {1}'.format(asd_id, node.ip))
        model_osd = None
        for disk in node.disks:
            for asd in disk.osds:
                if asd.osd_id == asd_id:
                    model_osd = asd
                    break
            if model_osd is not None:
                break
        if model_osd is not None:
            alba_backend = model_osd.alba_backend
        else:
            alba_backend = None

        asds = {}
        try:
            asds = node.client.get_asds()
        except (requests.ConnectionError, requests.Timeout, InvalidCredentialsError):
            AlbaNodeController._logger.warning('Could not connect to node {0} to validate ASD'.format(node.guid))
        partition_alias = None
        for alias, asd_ids in asds.iteritems():
            if asd_id in asd_ids:
                partition_alias = alias
                break

        if alba_backend is not None:
            if expected_safety is None:
                AlbaNodeController._logger.warning('Skipping safety check for ASD {0} on backend {1} - this is dangerous'.format(asd_id, alba_backend.guid))
            else:
                final_safety = AlbaController.calculate_safety(alba_backend_guid=alba_backend.guid,
                                                               removal_osd_ids=[asd_id])
                safety_lost = final_safety['lost']
                safety_crit = final_safety['critical']
                if (safety_crit != 0 or safety_lost != 0) and (safety_crit != expected_safety['critical'] or safety_lost != expected_safety['lost']):
                    raise RuntimeError('Cannot remove ASD {0} as the current safety is not as expected ({1} vs {2})'.format(asd_id, final_safety, expected_safety))
                AlbaNodeController._logger.debug('Safety OK for ASD {0} on backend {1}'.format(asd_id, alba_backend.guid))
            AlbaNodeController._logger.debug('Purging ASD {0} on backend {1}'.format(asd_id, alba_backend.guid))
            AlbaController.remove_units(alba_backend_guid=alba_backend.guid,
                                        osd_ids=[asd_id])
        else:
            AlbaNodeController._logger.warning('Could not match ASD {0} to any backend. Cannot purge'.format(asd_id))

        disk_data = None
        if partition_alias is not None:
            AlbaNodeController._logger.debug('Removing ASD {0} from disk {1}'.format(asd_id, partition_alias))
            for device_info in node.client.get_disks().itervalues():
                if partition_alias in device_info['partition_aliases']:
                    disk_data = device_info
                    result = node.client.delete_asd(disk_id=device_info['aliases'][0].split('/')[-1],
                                                    asd_id=asd_id)
                    if result['_success'] is False:
                        raise RuntimeError('Error removing ASD: {0}'.format(result['_error']))
            if disk_data == {}:
                raise RuntimeError('Failed to find disk for partition with alias {0}'.format(partition_alias))
        else:
            AlbaNodeController._logger.warning('Could not remove ASD from remote node (node down)'.format(asd_id))

        if Configuration.exists(AlbaNodeController.ASD_CONFIG.format(asd_id), raw=True):
            Configuration.delete(AlbaNodeController.ASD_CONFIG_DIR.format(asd_id), raw=True)

        if model_osd is not None:
            model_osd.delete()
        if alba_backend is not None:
            alba_backend.invalidate_dynamics()
            alba_backend.backend.invalidate_dynamics()
        if node.storagerouter is not None:
            DiskController.sync_with_reality(storagerouter_guid=node.storagerouter_guid)

        return [] if disk_data is None else disk_data.get('aliases', [])

    @staticmethod
    @celery.task(name='albanode.reset_asd')
    def reset_asd(node_guid, asd_id, expected_safety):
        """
        Removes and re-adds an ASD to a Disk
        :param node_guid: Guid of the node to reset an ASD of
        :type node_guid: str
        :param asd_id: ASD to reset
        :type asd_id: str
        :param expected_safety: Expected safety after having reset the disk
        :type expected_safety: dict
        :return: None
        """
        node = AlbaNode(node_guid)
        disk_aliases = AlbaNodeController.remove_asd(node_guid=node_guid,
                                                     asd_id=asd_id,
                                                     expected_safety=expected_safety)
        if len(disk_aliases) == 0:
            return
        try:
            result = node.client.add_asd(disk_id=disk_aliases[0].split('/')[-1])
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
        :param node_guid: Guid of the node to restart an ASD on
        :type node_guid: str
        :param asd_id: ID of the ASD to restart
        :type asd_id: str
        :return: None
        """
        node = AlbaNode(node_guid)
        try:
            asds = node.client.get_asds()
        except (requests.ConnectionError, requests.Timeout):
            AlbaNodeController._logger.warning('Could not connect to node {0} to validate ASD'.format(node.guid))
            raise

        partition_alias = None
        for alias, asd_ids in asds.iteritems():
            if asd_id in asd_ids:
                partition_alias = alias
                break
        if partition_alias is None:
            AlbaNodeController._logger.error('Could not locate ASD {0} on node {1}'.format(asd_id, node_guid))
            raise RuntimeError('Could not locate ASD {0} on node {1}'.format(asd_id, node_guid))

        device_alias = None
        for disk_info in node.client.get_disks().itervalues():
            if partition_alias in disk_info['partition_aliases']:
                device_alias = disk_info['aliases'][0]
                break
        if device_alias is None:
            raise RuntimeError('Failed to retrieve alias for the device related to partition {0}'.format(partition_alias))

        result = node.client.restart_asd(disk_id=device_alias.split('/')[-1], asd_id=asd_id)
        if result['_success'] is False:
            AlbaNodeController._logger.error('Error restarting ASD: {0}'.format(result['_error']))
            raise RuntimeError(result['_error'])

    @staticmethod
    @celery.task(name='albanode.restart_disk')
    def restart_disk(node_guid, device_alias):
        """
        Restarts a disk
        :param node_guid: Guid of the node to restart a disk of
        :type node_guid: str
        :param device_alias: Alias of the device to restart  (eg: /dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0)
        :type device_alias: str
        :return: None
        """
        node = AlbaNode(node_guid)
        device_id = device_alias.split('/')[-1]
        AlbaNodeController._logger.debug('Restarting disk {0} at node {1}'.format(device_alias, node.ip))
        try:
            if device_id not in node.client.get_disks():
                AlbaNodeController._logger.exception('Disk {0} not available for restart on node {1}'.format(device_alias, node.ip))
                raise RuntimeError('Could not find disk')
        except (requests.ConnectionError, requests.Timeout):
            AlbaNodeController._logger.warning('Could not connect to node {0} to validate disk'.format(node.guid))
            raise

        result = node.client.restart_disk(disk_id=device_id)
        if result['_success'] is False:
            raise RuntimeError('Error restarting disk: {0}'.format(result['_error']))
        for backend in AlbaBackendList.get_albabackends():
            backend.invalidate_dynamics()

    @staticmethod
    @add_hooks('nodeinstallation', ['firstnode', 'extranode'])
    @add_hooks('plugin', ['postinstall'])
    def model_albanodes(**kwargs):
        """
        Add all ALBA nodes known to the config platform to the model
        :param kwargs: Kwargs containing information regarding the node
        :type kwargs: dict
        :return: None
        """
        _ = kwargs
        if Configuration.dir_exists('/ovs/alba/asdnodes'):
            for node_id in Configuration.list('/ovs/alba/asdnodes'):
                node = AlbaNodeList.get_albanode_by_node_id(node_id)
                if node is None:
                    node = AlbaNode()
                main_config = Configuration.get('/ovs/alba/asdnodes/{0}/config/main'.format(node_id))
                node.type = 'ASD'
                node.node_id = node_id
                node.ip = main_config['ip']
                node.port = main_config['port']
                node.username = main_config['username']
                node.password = main_config['password']
                node.storagerouter = StorageRouterList.get_by_ip(main_config['ip'])
                node.save()

    @staticmethod
    @celery.task(name='albanode.get_logfiles')
    def get_logfiles(albanode_guid, local_storagerouter_guid):
        """
        Collects logs, moves them to a web-accessible location and returns log tgz's filename
        :param albanode_guid: Alba Node guid to retrieve log files on
        :type albanode_guid: str
        :param local_storagerouter_guid: Guid of the StorageRouter on which the collect logs was initiated, eg: through the GUI
        :type local_storagerouter_guid: str
        :return: Name of tgz containing the logs
        :rtype: str
        """
        web_path = '/opt/OpenvStorage/webapps/frontend/downloads'
        alba_node = AlbaNode(albanode_guid)
        logfile_name = alba_node.client.get_logs()['filename']
        download_url = 'https://{0}:{1}@{2}:{3}/downloads/{4}'.format(alba_node.username, alba_node.password, alba_node.ip, alba_node.port, logfile_name)

        client = SSHClient(endpoint=StorageRouter(local_storagerouter_guid), username='root')
        client.dir_create(web_path)
        client.run(['wget', download_url, '--directory-prefix', web_path, '--no-check-certificate'])
        client.run(['chmod', '666', '{0}/{1}'.format(web_path, logfile_name)])
        return logfile_name
