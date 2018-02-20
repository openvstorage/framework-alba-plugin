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
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.hybrids.albanodecluster import AlbaNodeCluster
from ovs.dal.hybrids.albaosd import AlbaOSD
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.albaosdlist import AlbaOSDList
from ovs.extensions.generic.configuration import Configuration
from ovs_extensions.generic.exceptions import NotFoundError
from ovs.extensions.generic.logger import Logger
from ovs.extensions.generic.sshclient import UnableToConnectException
from ovs_extensions.generic.toolbox import ExtensionsToolbox
from ovs.lib.alba import AlbaController
from ovs.lib.disk import DiskController
from ovs.lib.helpers.decorators import ovs_task


class AlbaNodeClusterController(object):
    """
    Contains all BLL related to ALBA nodes
    """
    _logger = Logger('lib')
    ASD_CONFIG_DIR = '/ovs/alba/asds/{0}'
    ASD_CONFIG = '{0}/config'.format(ASD_CONFIG_DIR)

    @staticmethod
    @ovs_task(name='albanodecluster.create_new')
    def create(name):
        """
        Creates a new AlbaNodeCluster
        :param name: Name of the AlbaNodeCluster
        :return: Newly created instance guid
        :rtype: basestring
        """
        an_cluster = AlbaNodeCluster()
        an_cluster.name = name
        an_cluster.save()
        return an_cluster.guid

    @staticmethod
    @ovs_task(name='albanodecluster.register_node')
    def register_node(node_cluster_guid, node_id):
        """
        Register a AlbaNode to the AlbaNodeCluster
        :param node_cluster_guid: Guid of the AlbaNodeCluster to add the node to
        :type node_cluster_guid: basestring
        :param node_id: ID of the ALBA node to register
        :type node_id: basestring
        :return: None
        :rtype: NoneType
        """
        an_cluster = AlbaNodeCluster(node_cluster_guid)
        an_node = AlbaNodeList.get_albanode_by_node_id(node_id)
        # Validation
        for slot_id, slot_info in an_node.stack.iteritems():
            for osd_id, osd_info in slot_info.iteritems():
                claimed_by = osd_info.get('claimed_by')
                if claimed_by is not None:  # Either UNKNOWN or a GUID:
                    if claimed_by == AlbaNode.OSD_STATUSES.UNKNOWN:
                        raise RuntimeError('Unable to link AlbaNode {0}. No information could be retrieved about OSD {1}'.format(node_id, osd_id))
                    raise RuntimeError('Unable to link AlbaNode {0} because it already has OSDs which are claimed'.format(node_id))
        an_node.alba_node_cluster = an_cluster
        an_node.save()

    @staticmethod
    @ovs_task(name='albanodecluster.unregister_node')
    def unregister_node(node_cluster_guid, node_id):
        """
        Unregisters an AlbaNode from the AlbaNodeCluster
        This will update the cluster to no longer work with active/passive
        :param node_cluster_guid: Guid of the AlbaNodeCluster to add the node to
        :type node_cluster_guid: basestring
        :param node_id: ID of the ALBA node to register
        :type node_id: basestring
        :return:
        """
        _ = node_cluster_guid
        an_node = AlbaNodeList.get_albanode_by_node_id(node_id)
        an_node.alba_node_cluster = None
        an_node.save()
        raise NotImplementedError('Actions after removing the relation has not yet been implemented')
        # @Todo implement reverting active/passive logic

    @staticmethod
    @ovs_task(name='albanodecluster.remove_cluster')
    def remove_cluster(node_cluster_guid):
        """
        Removes an AlbaNodeCluster
        :param node_cluster_guid: Guid of the AlbaNodeCluster to remove
        :type node_cluster_guid: basestring
        :return: None
        :rtype: NoneType
        """
        an_cluster = AlbaNodeCluster(node_cluster_guid)
        if len(an_cluster.alba_nodes) > 0:
            raise RuntimeError('The following Alba Nodes are still attached to the cluster:\n - {0}'
                               .format('\n - '.join(an_node.node_id for an_node in an_cluster.alba_nodes)))
        an_cluster.delete()

    @staticmethod
    @ovs_task(name='albanodecluster.fill_slots')
    def fill_slots(node_cluster_guid, slot_information, metadata=None):
        """
        Creates 1 or more new OSDs
        :param node_cluster_guid: Guid of the node cluster to which the disks belong
        :type node_cluster_guid: basestring
        :param slot_information: Information about the amount of OSDs to add to each Slot
        :type slot_information: list
        :param metadata: Metadata to add to the OSD (connection information for remote Backend, general Backend information)
        :type metadata: dict
        :return: None
        :rtype: NoneType
        """
        raise NotImplementedError('Filling slots of a cluster is not yet supported')
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
                if mtype == 'integer':
                    required_params[key] = (int, None)
                elif mtype == 'osd_type':
                    required_params[key] = (str, AlbaOSD.OSD_TYPES.keys())
                elif mtype == 'ip':
                    required_params[key] = (str, ExtensionsToolbox.regex_ip)
                elif mtype == 'port':
                    required_params[key] = (int, {'min': 1, 'max': 65535})
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
                node.client.fill_slot(slot_id=slot_info['slot_id'],
                                      extra=dict((key, slot_info[key]) for key in node.node_metadata['fill_metadata']))
            elif node.node_metadata['fill_add'] is True:
                # Fill the slot
                node.client.fill_slot(slot_id=slot_info['slot_id'],
                                      extra=dict((key, slot_info[key]) for key in node.node_metadata['fill_add_metadata']))

                # And add/claim the OSD
                AlbaController.add_osds(alba_backend_guid=slot_info['alba_backend_guid'],
                                        osds=[slot_info],
                                        alba_node_guid=node_guid,
                                        metadata=metadata)
        node.invalidate_dynamics('stack')

    @staticmethod
    @ovs_task(name='albanodecluster.remove_slot', ensure_single_info={'mode': 'CHAINED'})
    def remove_slot(node_cluster_guid, slot_id):
        """
        Removes a disk
        :param node_cluster_guid: Guid of the node cluster to remove a disk from
        :type node_cluster_guid: str
        :param slot_id: Slot ID
        :type slot_id: str
        :return: None
        :rtype: NoneType
        """
        raise NotImplementedError('Removing slots of a cluster is not yet supported')
        # Verify client connectivity
        node = AlbaNode(node_guid)
        osds = [osd for osd in node.osds if osd.slot_id == slot_id]
        if len(osds) > 0:
            raise RuntimeError('A slot with claimed OSDs can\'t be removed')

        node.client.clear_slot(slot_id)

        node.invalidate_dynamics()
        if node.storagerouter is not None:
            DiskController.sync_with_reality(storagerouter_guid=node.storagerouter_guid)

    @staticmethod
    @ovs_task(name='albanodecluster.remove_osd', ensure_single_info={'mode': 'CHAINED'})
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
        raise NotImplementedError('Removing an from the cluster is not yet supported')
        # Retrieve corresponding OSD in model
        node = AlbaNode(node_guid)
        AlbaNodeClusterController._logger.debug('Removing OSD {0} at node {1}'.format(osd_id, node.ip))
        osd = AlbaOSDList.get_by_osd_id(osd_id)
        alba_backend = osd.alba_backend

        if expected_safety is None:
            AlbaNodeClusterController._logger.warning('Skipping safety check for OSD {0} on backend {1} - this is dangerous'.format(osd_id, alba_backend.guid))
        else:
            final_safety = AlbaController.calculate_safety(alba_backend_guid=alba_backend.guid,
                                                           removal_osd_ids=[osd_id])
            safety_lost = final_safety['lost']
            safety_crit = final_safety['critical']
            if (safety_crit != 0 or safety_lost != 0) and (safety_crit != expected_safety['critical'] or safety_lost != expected_safety['lost']):
                raise RuntimeError('Cannot remove OSD {0} as the current safety is not as expected ({1} vs {2})'.format(osd_id, final_safety, expected_safety))
            AlbaNodeClusterController._logger.debug('Safety OK for OSD {0} on backend {1}'.format(osd_id, alba_backend.guid))
        AlbaNodeClusterController._logger.debug('Purging OSD {0} on backend {1}'.format(osd_id, alba_backend.guid))
        AlbaController.remove_units(alba_backend_guid=alba_backend.guid,
                                    osd_ids=[osd_id])

        # Delete the OSD
        result = node.client.delete_osd(slot_id=osd.slot_id,
                                        osd_id=osd_id)
        if result['_success'] is False:
            raise RuntimeError('Error removing OSD: {0}'.format(result['_error']))

        # Clean configuration management and model - Well, just try it at least
        if Configuration.exists(AlbaNodeClusterController.ASD_CONFIG.format(osd_id), raw=True):
            Configuration.delete(AlbaNodeClusterController.ASD_CONFIG_DIR.format(osd_id), raw=True)

        osd.delete()
        node.invalidate_dynamics()
        if alba_backend is not None:
            alba_backend.invalidate_dynamics()
            alba_backend.backend.invalidate_dynamics()
        if node.storagerouter is not None:
            try:
                DiskController.sync_with_reality(storagerouter_guid=node.storagerouter_guid)
            except UnableToConnectException:
                AlbaNodeClusterController._logger.warning('Skipping disk sync since StorageRouter {0} is offline'.format(node.storagerouter.name))

        return [osd.slot_id]

    @staticmethod
    @ovs_task(name='albanodecluster.reset_osd')
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
        raise NotImplementedError('Resetting an OSD is not yet implemented')
        node = AlbaNode(node_guid)
        osd = AlbaOSDList.get_by_osd_id(osd_id)
        fill_slot_extra = node.client.build_slot_params(osd)
        disk_aliases = AlbaNodeClusterController.remove_osd(node_guid=node_guid, osd_id=osd_id, expected_safety=expected_safety)
        if len(disk_aliases) == 0:
            return
        try:
            node.client.fill_slot(osd.slot_id, fill_slot_extra)
        except (requests.ConnectionError, requests.Timeout):
            AlbaNodeClusterController._logger.warning('Could not connect to node {0} to (re)configure ASD'.format(node.guid))
        except NotFoundError:
            # Can occur when the slot id could not be matched with an existing slot on the alba-asd manager
            # This error can be anticipated when the status of the osd would be 'missing' in the nodes stack but that would be too much overhead
            message = 'Could not add a new OSD. The requested slot {0} could not be found'.format(osd.slot_id)
            AlbaNodeClusterController._logger.warning(message)
            raise RuntimeError('{0}. Slot {1} might no longer be present on Alba node {2}'.format(message, osd.slot_id, node_guid))
        node.invalidate_dynamics('stack')

    @staticmethod
    @ovs_task(name='albanodecluster.restart_osd')
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
        raise NotImplementedError('Restarting an OSD is not yet supported')
        node = AlbaNode(node_guid)
        osd = AlbaOSDList.get_by_osd_id(osd_id)
        if osd.alba_node_guid != node.guid:
            raise RuntimeError('Could not locate OSD {0} on node {1}'.format(osd_id, node_guid))

        try:
            result = node.client.restart_osd(osd.slot_id, osd.osd_id)
            if result['_success'] is False:
                AlbaNodeClusterController._logger.error('Error restarting OSD: {0}'.format(result['_error']))
                raise RuntimeError(result['_error'])
        except (requests.ConnectionError, requests.Timeout):
            AlbaNodeClusterController._logger.warning('Could not connect to node {0} to restart OSD'.format(node.guid))
            raise

    @staticmethod
    @ovs_task(name='albanodecluster.restart_slot')
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
        raise NotImplementedError('Restarting a slot is not yet implemented')
        node = AlbaNode(node_guid)
        AlbaNodeClusterController._logger.debug('Restarting slot {0} on node {1}'.format(slot_id, node.ip))
        try:
            if slot_id not in node.client.get_stack():
                AlbaNodeClusterController._logger.exception('Slot {0} not available for restart on ALBA Node {1}'.format(slot_id, node.ip))
                raise RuntimeError('Could not find slot')
        except (requests.ConnectionError, requests.Timeout):
            AlbaNodeClusterController._logger.warning('Could not connect to node {0} to validate slot'.format(node.guid))
            raise

        result = node.client.restart_slot(slot_id=slot_id)
        if result['_success'] is False:
            raise RuntimeError('Error restarting slot: {0}'.format(result['_error']))
        for backend in AlbaBackendList.get_albabackends():
            backend.invalidate_dynamics()
