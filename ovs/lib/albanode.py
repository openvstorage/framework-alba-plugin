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

import string
import random
import requests
from ovs.dal.hybrids.albadisk import AlbaDisk
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.hybrids.albaosd import AlbaOSD
from ovs.dal.hybrids.diskpartition import DiskPartition
from ovs.dal.hybrids.storagerouter import StorageRouter
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.albaosdlist import AlbaOSDList
from ovs.dal.lists.disklist import DiskList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs.extensions.generic.configuration import Configuration
from ovs.extensions.generic.sshclient import SSHClient, UnableToConnectException
from ovs.extensions.plugins.asdmanager import InvalidCredentialsError
from ovs.lib.alba import AlbaController
from ovs.lib.disk import DiskController
from ovs.lib.helpers.toolbox import Toolbox
from ovs.lib.helpers.decorators import add_hooks, ovs_task
from ovs.log.log_handler import LogHandler


class AlbaNodeController(object):
    """
    Contains all BLL related to ALBA nodes
    """
    _logger = LogHandler.get('lib', name='albanode')
    ASD_CONFIG_DIR = '/ovs/alba/asds/{0}'
    ASD_CONFIG = '{0}/config'.format(ASD_CONFIG_DIR)

    @staticmethod
    @ovs_task(name='albanode.register')
    def register(node_id=None, node_type=None, name=None):
        """
        Adds a Node with a given node_id to the model
        :param node_id: ID of the ALBA node
        :type node_id: str
        :param node_type: Type of the node to create
        :type node_type: str
        :param name: Optional name of the node
        :type name: str
        :return: None
        :rtype: NoneType
        """
        if node_type == AlbaNode.NODE_TYPES.GENERIC:
            node = AlbaNode()
            node.name = name
            node.node_id = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(32))
            node.type = AlbaNode.NODE_TYPES.GENERIC
            node.save()
        else:
            if node_id is None:
                raise RuntimeError('A node_id must be given for type ASD')
            node = AlbaNodeList.get_albanode_by_node_id(node_id)
            if node is None:
                main_config = Configuration.get('/ovs/alba/asdnodes/{0}/config/main'.format(node_id))
                node = AlbaNode()
                node.name = name
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
            node.type = AlbaNode.NODE_TYPES.ASD
            node.save()
        AlbaController.checkup_maintenance_agents.delay()

    @staticmethod
    @ovs_task(name='albanode.remove_node')
    def remove_node(node_guid):
        """
        Removes an ALBA node
        :param node_guid: Guid of the ALBA node to remove
        :type node_guid: str
        :return: None
        :rtype: NoneType
        """
        node = AlbaNode(node_guid)
        if node.type == AlbaNode.NODE_TYPES.ASD:
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

        node.delete()
        for alba_backend in AlbaBackendList.get_albabackends():
            alba_backend.invalidate_dynamics(['live_status'])
            alba_backend.backend.invalidate_dynamics(['live_status'])
        AlbaController.checkup_maintenance_agents.delay()

    @staticmethod
    @ovs_task(name='albanode.replace_node')
    def replace_node(old_node_guid, new_node_id):
        """
        Replace an ALBA node
        :param old_node_guid: Guid of the old ALBA node being replaced
        :type old_node_guid: str
        :param new_node_id: ID of the new ALBA node
        :type new_node_id: str
        :return: None
        :rtype: NoneType
        """
        AlbaNodeController.remove_node(node_guid=old_node_guid)
        AlbaNodeController.register(node_id=new_node_id)

    @staticmethod
    @ovs_task(name='albanode.fill_slot')
    def fill_slot(node_guid, slot_id, osds, metadata=None):
        """
        Creates a new osd
        :param node_guid: Guid of the node to which the disks belong
        :type node_guid: str
        :param slot_id: Slot to fill
        :type slot_id: int
        :param osds: OSDs to "put in the slot"
        :type osds: list
        :param metadata: Metadata to add to the OSD (connection information for remote Backend, general Backend information)
        :type metadata: dict
        :return:
        """
        node = AlbaNode(node_guid)
        slot_metadata = node.node_metadata['slots']
        required_params = {}
        can_be_filled = False
        for flow in ['fill', 'fill_add']:
            if slot_metadata[flow] is False:
                continue
            can_be_filled = True
            if flow == 'fill_add':
                required_params['alba_backend_guid'] = (str, None)
            for key, mtype in slot_metadata['{0}_metadata'.format(flow)].iteritems():
                rtype = None
                if mtype == 'integer':
                    rtype = (int, None)
                elif mtype == 'osd_type':
                    rtype = (str, AlbaOSD.OSD_TYPES.keys())
                elif mtype == 'ip':
                    rtype = (str, Toolbox.regex_ip)
                elif mtype == 'port':
                    rtype = (int, {'min': 1, 'max': 65536})
                if rtype is not None:
                    required_params[key] = rtype
        if can_be_filled is False:
            raise ValueError('The given node does not support filling slots')

        validation_reasons = []
        for osd in osds:
            try:
                Toolbox.verify_required_params(required_params=required_params,
                                               actual_params=osd)
            except RuntimeError as ex:
                validation_reasons.append(str(ex))
        if len(validation_reasons) > 0:
            raise ValueError('Missing required paramater:\n *{0}'.format('\n* '.join(('{0}'.format(reason) for reason in validation_reasons))))

        osds_to_claim = {}
        for osd in osds:
            osd['slot_id'] = slot_id
            if slot_metadata['fill'] is True:
                # Only filling is required
                node.client.fill_slot(slot_id=slot_id,
                                      extra=dict((key, osd[key]) for key in slot_metadata['fill_metadata']))
            elif slot_metadata['fill_add'] is True:
                # Fill the slot
                node.client.fill_slot(slot_id=slot_id,
                                      extra=dict((key, osd[key]) for key in slot_metadata['fill_add_metadata']))
                # And add/claim the OSD
                if osd['alba_backend_guid'] not in osds_to_claim:
                    osds_to_claim[osd['alba_backend_guid']] = []
                osds_to_claim[osd['alba_backend_guid']].append(osd)
        for alba_backend_guid, osds in osds_to_claim.iteritems():
            AlbaController.add_osds(alba_backend_guid, node_guid, osds, metadata)

    @staticmethod
    @ovs_task(name='albanode.initialize_disk')
    def initialize_disks(node_guid, disks):
        """
        Initializes 1 or multiple disks
        :param node_guid: Guid of the node to which the disks belong
        :type node_guid: str
        :param disks: Disks to initialize  (key: device_alias, value: amount of ASDs to deploy)
        :type disks: dict
        :return: Dict of all failures with as key the disk name, and as value the error
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
    @ovs_task(name='albanode.remove_disk', ensure_single_info={'mode': 'CHAINED'})
    def remove_disk(node_guid, device_alias):
        """
        Removes a disk
        :param node_guid: Guid of the node to remove a disk from
        :type node_guid: str
        :param device_alias: Alias of the device to remove  (eg: /dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0)
        :type device_alias: str
        :return: None
        :rtype: NoneType
        """
        # Verify client connectivity
        node = AlbaNode(node_guid)
        online_node = True
        try:
            node.client.get_disks()
        except (requests.ConnectionError, requests.Timeout, InvalidCredentialsError):
            AlbaNodeController._logger.warning('Could not connect to node {0} to validate disks'.format(node.guid))
            online_node = False

        # Retrieve ASD information for the ALBA Disk
        device_id = device_alias.split('/')[-1]
        call_exists = False
        all_alba_backends = AlbaBackendList.get_albabackends()
        if online_node is True:
            asds_in_use = node.client.get_claimed_asds(disk_id=device_id)
            call_exists = asds_in_use.pop('call_exists')
            if len(asds_in_use) > 0:
                id_name_map = dict((ab.alba_id, ab.name) for ab in all_alba_backends)
                reasons = set()
                for info in asds_in_use.itervalues():
                    if info in id_name_map:
                        reasons.add('ASDs claimed by Backend {0}'.format(id_name_map[info]))
                    else:
                        reasons.add(info)
                raise RuntimeError('Disk {0} on ALBA node {1} with IP {2} cannot be deleted because:\n - {3}'.format(device_alias, node.node_id, node.ip, '\n - '.join(reasons)))

        if online_node is False or call_exists is False:  # Talking to older client, so failed to retrieve the claimed ASDs
            for alba_backend in all_alba_backends:
                local_stack = alba_backend.local_stack
                if node.node_id in local_stack and device_id in local_stack[node.node_id]:
                    for asd_info in local_stack[node.node_id][device_id]['asds'].values():
                        if (online_node is True and asd_info.get('status') != 'available') or (online_node is False and asd_info.get('status_detail') == 'nodedown'):
                            raise RuntimeError('Disk {0} on ALBA node {1} with IP {2} has still some non-available ASDs'.format(device_alias, node.node_id, node.ip))

        # Retrieve the Disk from the framework model matching the ALBA Disk
        disk_to_clear = None
        for disk in DiskList.get_disks():
            if device_alias in disk.aliases:
                disk_to_clear = disk
                break

        # Remove the ALBA Disk making use of the ASD Manager Client
        if online_node is True:
            partition_aliases = None if disk_to_clear is None or len(disk_to_clear.partitions) == 0 else disk_to_clear.partitions[0].aliases
            result = node.client.remove_disk(disk_id=device_id, partition_aliases=partition_aliases)
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
        for alba_backend in all_alba_backends:
            alba_backend.invalidate_dynamics('local_stack')
        node.invalidate_dynamics()
        if node.storagerouter is not None and online_node is True:
            DiskController.sync_with_reality(storagerouter_guid=node.storagerouter_guid)

    @staticmethod
    @ovs_task(name='albanode.remove_osd', ensure_single_info={'mode': 'CHAINED'})
    def remove_osd(node_guid, osd_id, expected_safety):
        """
        Removes an OSD
        :param node_guid: Guid of the node to remove an OSD from
        :type node_guid: str
        :param osd_id: ID of the OSD to remove
        :type osd_id: str
        :param expected_safety: Expected safety after having removed the OSD
        :type expected_safety: dict or None
        :return: Aliases of the disk on which the OSD was removed
        :rtype: list
        """
        # Retrieve corresponding OSD in model
        node = AlbaNode(node_guid)
        AlbaNodeController._logger.debug('Removing OSD {0} at node {1}'.format(osd_id, node.ip))
        osd = AlbaOSDList.get_by_osd_id(osd_id)
        alba_backend = osd.alba_backend

        if expected_safety is None:
            AlbaNodeController._logger.warning('Skipping safety check for OSD {0} on backend {1} - this is dangerous'.format(osd_id, alba_backend.guid))
        else:
            final_safety = AlbaController.calculate_safety(alba_backend_guid=alba_backend.guid,
                                                           removal_osd_ids=[osd_id])
            safety_lost = final_safety['lost']
            safety_crit = final_safety['critical']
            if (safety_crit != 0 or safety_lost != 0) and (safety_crit != expected_safety['critical'] or safety_lost != expected_safety['lost']):
                raise RuntimeError('Cannot remove OSD {0} as the current safety is not as expected ({1} vs {2})'.format(osd_id, final_safety, expected_safety))
            AlbaNodeController._logger.debug('Safety OK for OSD {0} on backend {1}'.format(osd_id, alba_backend.guid))
        AlbaNodeController._logger.debug('Purging OSD {0} on backend {1}'.format(osd_id, alba_backend.guid))
        AlbaController.remove_units(alba_backend_guid=alba_backend.guid,
                                    osd_ids=[osd_id])

        # Delete the OSD
        result = node.client.delete_osd(slot_id=osd.slot_id,
                                        osd_id=osd_id)
        if result['_success'] is False:
            raise RuntimeError('Error removing OSD: {0}'.format(result['_error']))

        # Clean configuration management and model - Well, just try it at least
        if Configuration.exists(AlbaNodeController.ASD_CONFIG.format(osd_id), raw=True):
            Configuration.delete(AlbaNodeController.ASD_CONFIG_DIR.format(osd_id), raw=True)

        if osd is not None:
            osd.delete()
        if alba_backend is not None:
            alba_backend.invalidate_dynamics()
            alba_backend.backend.invalidate_dynamics()
        if node.storagerouter is not None:
            try:
                DiskController.sync_with_reality(storagerouter_guid=node.storagerouter_guid)
            except UnableToConnectException:
                AlbaNodeController._logger.warning('Skipping disk sync since StorageRouter {0} is offline'.format(node.storagerouter.name))

        return [osd.slot_id]

    @staticmethod
    @ovs_task(name='albanode.reset_asd')
    def reset_osd(node_guid, osd_id, expected_safety):
        """
        Removes and re-adds an OSD to a Disk
        :param node_guid: Guid of the node to reset an OSD of
        :type node_guid: str
        :param osd_id: OSD to reset
        :type osd_id: str
        :param expected_safety: Expected safety after having reset the disk
        :type expected_safety: dict
        :return: None
        :rtype: NoneType
        """
        node = AlbaNode(node_guid)
        osd = AlbaOSDList.get_by_osd_id(osd_id)
        fill_slot_extra = node.client.build_slot_params(osd)
        disk_aliases = AlbaNodeController.remove_osd(node_guid=node_guid,
                                                     osd_id=osd_id,
                                                     expected_safety=expected_safety)
        if len(disk_aliases) == 0:
            return
        try:
            node.client.fill_slot(osd.slot_id, fill_slot_extra)
        except (requests.ConnectionError, requests.Timeout):
            AlbaNodeController._logger.warning('Could not connect to node {0} to (re)configure ASD'.format(node.guid))

    @staticmethod
    @ovs_task(name='albanode.restart_osd')
    def restart_osd(node_guid, osd_id):
        """
        Restarts an OSD on a given Node
        :param node_guid: Guid of the node to restart an OSD on
        :type node_guid: str
        :param osd_id: ID of the OSD to restart
        :type osd_id: str
        :return: None
        :rtype: NoneType
        """
        node = AlbaNode(node_guid)
        osd = AlbaOSDList.get_by_osd_id(osd_id)
        if osd.alba_node_guid != node.guid:
            raise RuntimeError('Could not locate OSD {0} on node {1}'.format(osd_id, node_guid))

        try:
            result = node.client.restart_osd(osd.slot_id, osd.osd_id)
            if result['_success'] is False:
                AlbaNodeController._logger.error('Error restarting OSD: {0}'.format(result['_error']))
                raise RuntimeError(result['_error'])
        except (requests.ConnectionError, requests.Timeout):
            AlbaNodeController._logger.warning('Could not connect to node {0} to restart OSD'.format(node.guid))
            raise

    @staticmethod
    @ovs_task(name='albanode.restart_disk')
    def restart_disk(node_guid, device_alias):
        """
        Restarts a disk
        :param node_guid: Guid of the node to restart a disk of
        :type node_guid: str
        :param device_alias: Alias of the device to restart  (eg: /dev/disk/by-path/pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0)
        :type device_alias: str
        :return: None
        :rtype: NoneType
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
        :rtype: NoneType
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
    @ovs_task(name='albanode.get_logfiles')
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
