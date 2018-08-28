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

import uuid
import string
import random
import requests
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.hybrids.albaosd import AlbaOSD
from ovs.dal.hybrids.diskpartition import DiskPartition
from ovs.dal.hybrids.storagerouter import StorageRouter
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.albaosdlist import AlbaOSDList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs.extensions.generic.configuration import Configuration
from ovs_extensions.generic.exceptions import InvalidCredentialsError, NotFoundError
from ovs.extensions.generic.logger import Logger
from ovs.extensions.generic.sshclient import SSHClient, UnableToConnectException
from ovs_extensions.generic.toolbox import ExtensionsToolbox
from ovs.lib.alba import AlbaController
from ovs.lib.disk import DiskController
from ovs.constants.albanode import ASD_CONFIG, ASD_CONFIG_DIR
from ovs.lib.helpers.decorators import add_hooks, ovs_task


class AlbaNodeController(object):
    """
    Contains all BLL related to ALBA nodes
    """
    _logger = Logger('lib')

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
            for slot_id, slot_info in node.stack.iteritems():
                for osd_id, osd_info in slot_info['osds'].iteritems():
                    if AlbaOSDList.get_by_osd_id(osd_id=osd_id) is not None:
                        AlbaNodeController.remove_osd(node_guid=node.guid, osd_id=osd_id, expected_safety=None)
                if slot_info['available'] is False:
                    AlbaNodeController.remove_slot(node_guid=node.guid, slot_id=slot_id)

            name_guid_map = dict((alba_backend.name, alba_backend.guid) for alba_backend in AlbaBackendList.get_albabackends())
            try:
                # This loop will delete the services AND their configuration from the configuration management
                node.invalidate_dynamics('maintenance_services')
                for alba_backend_name, service_info in node.maintenance_services.iteritems():
                    for service_name, status in service_info:
                        node.client.remove_maintenance_service(name=service_name, alba_backend_guid=name_guid_map.get(alba_backend_name))
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
    def generate_empty_slot(alba_node_guid):
        """
        Generates an empty slot on the alba node
        :param alba_node_guid: Guid of the AlbaNode to generate a slot on
        :type alba_node_guid: str
        :return: Slot information
        :rtype: dict
        """
        alba_node = AlbaNode(alba_node_guid)
        if alba_node.type != AlbaNode.NODE_TYPES.GENERIC:
            raise RuntimeError('An empty slot can only be generated for a generic node')
        return {str(uuid.uuid4()): {'status': alba_node.SLOT_STATUSES.EMPTY}}

    @staticmethod
    @ovs_task(name='albanode.fill_slots')
    def fill_slots(node_guid, slot_information, metadata=None):
        """
        Creates 1 or more new OSDs
        :param node_guid: Guid of the node to which the disks belong
        :type node_guid: str
        :param slot_information: Information about the amount of OSDs to add to each Slot
        :type slot_information: list
        :param metadata: Metadata to add to the OSD (connection information for remote Backend, general Backend information)
        :type metadata: dict
        :return: None
        :rtype: NoneType
        """
        metadata_type_validation = {'integer': (int, None),
                                    'osd_type': (str, AlbaOSD.OSD_TYPES.keys()),
                                    'ip': (str, ExtensionsToolbox.regex_ip),
                                    'port': (int, {'min': 1, 'max': 65535})}
        node = AlbaNode(node_guid)
        required_params = {'slot_id': (str, None)}
        can_be_filled = False
        for flow in ['fill', 'fill_add']:
            if node.node_metadata[flow] is False:
                continue
            can_be_filled = True
            if flow == 'fill_add':
                required_params['alba_backend_guid'] = (str, None)
            for key, mtype in node.node_metadata['{0}_metadata'.format(flow)].iteritems():
                if mtype in metadata_type_validation:
                    required_params[key] = metadata_type_validation[mtype]
        if can_be_filled is False:
            raise ValueError('The given node does not support filling slots')

        validation_reasons = []
        for slot_info in slot_information:
            try:
                ExtensionsToolbox.verify_required_params(required_params=required_params, actual_params=slot_info)
            except RuntimeError as ex:
                validation_reasons.append(str(ex))
        if len(validation_reasons) > 0:
            raise ValueError('Missing required parameter:\n *{0}'.format('\n* '.join(validation_reasons)))

        for slot_info in slot_information:
            if node.node_metadata['fill'] is True:
                # Only filling is required
                AlbaNodeController._fill_slot(node, slot_info['slot_id'], dict((key, slot_info[key]) for key in node.node_metadata['fill_metadata']))
            elif node.node_metadata['fill_add'] is True:
                # Fill the slot
                AlbaNodeController._fill_slot(node, slot_info['slot_id'], dict((key, slot_info[key]) for key in node.node_metadata['fill_add_metadata']))
                # And add/claim the OSD
                AlbaController.add_osds(alba_backend_guid=slot_info['alba_backend_guid'],
                                        osds=[slot_info],
                                        alba_node_guid=node_guid,
                                        metadata=metadata)
        node.invalidate_dynamics('stack')

    @classmethod
    def _fill_slot(cls, node, slot_id, extra):
        # type: (AlbaNode, str, any) -> None
        """
        Fills in the slots with ASDs and checks if the BACKEND role needs to be added
        :param node: The AlbaNode to fill on
        :type node: AlbaNode
        :param slot_id: ID of the slot to fill (which is an alias of the slot)
        :type slot_id: str
        :param extra: Extra information for filling
        :type extra: any
        :return: None
        :rtype: NoneType
        """
        node.client.fill_slot(slot_id=slot_id,
                              extra=extra)

        # Sync model
        if node.storagerouter is not None:
            stack = node.client.get_stack()  # type: dict
            DiskController.sync_with_reality(storagerouter_guid=node.storagerouter_guid)
            slot_information = stack.get(slot_id, {})
            slot_aliases = slot_information.get('aliases', [])
            for disk in node.storagerouter.disks:
                if set(disk.aliases).intersection(set(slot_aliases)):
                    partition = disk.partitions[0]
                    if DiskPartition.ROLES.BACKEND not in partition.roles:
                        partition.roles.append(DiskPartition.ROLES.BACKEND)
                        partition.save()

    @staticmethod
    @ovs_task(name='albanode.remove_slot', ensure_single_info={'mode': 'CHAINED'})
    def remove_slot(node_guid, slot_id):
        """
        Removes a disk
        :param node_guid: Guid of the node to remove a disk from
        :type node_guid: str
        :param slot_id: Slot ID
        :type slot_id: str
        :return: None
        :rtype: NoneType
        """
        # Verify client connectivity
        node = AlbaNode(node_guid)
        osds = [osd for osd in node.osds if osd.slot_id == slot_id]
        if len(osds) > 0:
            raise RuntimeError('A slot with claimed OSDs can\'t be removed')

        node.client.clear_slot(slot_id)

        node.invalidate_dynamics()
        # Sync model
        if node.storagerouter is not None:
            stack = node.client.get_stack()  # type: dict
            slot_information = stack.get(slot_id, {})
            slot_aliases = slot_information.get('aliases', [])
            for disk in node.storagerouter.disks:
                if set(disk.aliases).intersection(set(slot_aliases)):
                    partition = disk.partitions[0]
                    if DiskPartition.ROLES.BACKEND in partition.roles:
                        partition.roles.remove(DiskPartition.ROLES.BACKEND)
                        partition.save()
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
        if Configuration.exists(ASD_CONFIG.format(osd_id), raw=True):
            Configuration.delete(ASD_CONFIG_DIR.format(osd_id), raw=True)

        osd.delete()
        node.invalidate_dynamics()
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
    @ovs_task(name='albanode.reset_osd')
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
            AlbaNodeController._fill_slot(node, osd.slot_id, fill_slot_extra)
        except (requests.ConnectionError, requests.Timeout):
            AlbaNodeController._logger.warning('Could not connect to node {0} to (re)configure ASD'.format(node.guid))
        except NotFoundError:
            # Can occur when the slot id could not be matched with an existing slot on the alba-asd manager
            # This error can be anticipated when the status of the osd would be 'missing' in the nodes stack but that would be too much overhead
            message = 'Could not add a new OSD. The requested slot {0} could not be found'.format(osd.slot_id)
            AlbaNodeController._logger.warning(message)
            raise RuntimeError('{0}. Slot {1} might no longer be present on Alba node {2}'.format(message, osd.slot_id, node_guid))
        node.invalidate_dynamics('stack')

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
    @ovs_task(name='albanode.restart_slot')
    def restart_slot(node_guid, slot_id):
        """
        Restarts a slot
        :param node_guid: Guid of the ALBA Node to restart a slot on
        :type node_guid: str
        :param slot_id: ID of the slot (eg. pci-0000:03:00.0-sas-0x5000c29f4cf04566-lun-0)
        :type slot_id: str
        :return: None
        :rtype: NoneType
        """
        node = AlbaNode(node_guid)
        AlbaNodeController._logger.debug('Restarting slot {0} on node {1}'.format(slot_id, node.ip))
        try:
            if slot_id not in node.client.get_stack():
                AlbaNodeController._logger.exception('Slot {0} not available for restart on ALBA Node {1}'.format(slot_id, node.ip))
                raise RuntimeError('Could not find slot')
        except (requests.ConnectionError, requests.Timeout):
            AlbaNodeController._logger.warning('Could not connect to node {0} to validate slot'.format(node.guid))
            raise

        result = node.client.restart_slot(slot_id=slot_id)
        if result['_success'] is False:
            raise RuntimeError('Error restarting slot: {0}'.format(result['_error']))
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
