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
    def register_node(node_cluster_guid, node_id=None, node_ids=None):
        """
        Register a AlbaNode to the AlbaNodeCluster
        :param node_cluster_guid: Guid of the AlbaNodeCluster to add the node to
        :type node_cluster_guid: basestring
        :param node_id: ID of the ALBA node to register
        :type node_id: basestring
        :param node_ids: List of IDs of AlbaNodes to register
        :type node_ids: list[str]
        :return: None
        :rtype: NoneType
        """
        if all(x is None for x in [node_id, node_ids]):
            raise ValueError('Either node_id or node_ids must be given')
        if node_ids is None:
            node_ids = [node_id]
        an_cluster = AlbaNodeCluster(node_cluster_guid)
        messages = []
        for node_id in node_ids:
            try:
                an_node = AlbaNodeList.get_albanode_by_node_id(node_id)
                if an_node is None:
                    messages.append('No AlbaNode found with ID {0}'.format(node_id))
                    continue
                # Validation
                for slot_id, slot_info in an_node.stack.iteritems():
                    for osd_id, osd_info in slot_info['osds'].iteritems():
                        claimed_by = osd_info.get('claimed_by')
                        if claimed_by is not None:  # Either UNKNOWN or a GUID:
                            if claimed_by == AlbaNode.OSD_STATUSES.UNKNOWN:
                                raise RuntimeError('Unable to link AlbaNode {0}. No information could be retrieved about OSD {1}'.format(node_id, osd_id))
                            raise RuntimeError('Unable to link AlbaNode {0} because it already has OSDs which are claimed'.format(node_id))
                an_node.alba_node_cluster = an_cluster
                an_node.save()
            except Exception:
                message = 'Unhandled Exception occurred during the registering of AlbaNode with id {0} under AlbaNodeCluster {1}'.format(node_id, node_cluster_guid)
                messages.append(message)
                AlbaNodeClusterController._logger.exception(message)
        if len(messages) > 0:
            raise ValueError('Errors occurred while registering AlbaNodes with IDs {0}:\n - {1}'.format(node_ids, '\n - '.join(messages)))

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
    def fill_slots(node_cluster_guid, node_guid, slot_information, metadata=None):
        """
        Creates 1 or more new OSDs
        :param node_cluster_guid: Guid of the node cluster to which the disks belong
        :type node_cluster_guid: basestring
        :param node_guid: Guid of the AlbaNode to act as the 'active' side
        :type node_guid: basestring
        :param slot_information: Information about the amount of OSDs to add to each Slot
        :type slot_information: list
        :param metadata: Metadata to add to the OSD (connection information for remote Backend, general Backend information)
        :type metadata: dict
        :return: None
        :rtype: NoneType
        """
        node_cluster = AlbaNodeCluster(node_cluster_guid)
        # Check for the active side if it's part of the cluster
        active_node = AlbaNode(node_guid)
        if active_node not in node_cluster.alba_nodes:
            raise ValueError('The requested active AlbaNode is not part of AlbaNodeCluster {0}'.format(node_cluster.guid))
        required_params = {'slot_id': (str, None)}
        can_be_filled = False
        for flow in ['fill', 'fill_add']:
            if node_cluster.cluster_metadata[flow] is False:
                continue
            can_be_filled = True
            if flow == 'fill_add':
                required_params['alba_backend_guid'] = (str, None)
            for key, mtype in node_cluster.cluster_metadata['{0}_metadata'.format(flow)].iteritems():
                if mtype == 'integer':
                    required_params[key] = (int, None)
                elif mtype == 'osd_type':
                    required_params[key] = (str, AlbaOSD.OSD_TYPES.keys())
                elif mtype == 'ip':
                    required_params[key] = (str, ExtensionsToolbox.regex_ip)
                elif mtype == 'port':
                    required_params[key] = (int, {'min': 1, 'max': 65535})
        if can_be_filled is False:
            raise ValueError('The given node cluster does not support filling slots')

        validation_reasons = []
        for slot_info in slot_information:
            try:
                ExtensionsToolbox.verify_required_params(required_params=required_params, actual_params=slot_info)
            except RuntimeError as ex:
                validation_reasons.append(str(ex))
        if len(validation_reasons) > 0:
            raise ValueError('Missing required parameter:\n *{0}'.format('\n* '.join(validation_reasons)))

        for slot_info in slot_information:
            if node_cluster.cluster_metadata['fill'] is True:
                # Only filling is required
                active_node.client.fill_slot(slot_id=slot_info['slot_id'],
                                             extra=dict((key, slot_info[key]) for key in node_cluster.cluster_metadata['fill_metadata']))
            elif node_cluster.cluster_metadata['fill_add'] is True:
                # Fill the slot
                active_node.client.fill_slot(slot_id=slot_info['slot_id'],
                                             extra=dict((key, slot_info[key]) for key in node_cluster.cluster_metadata['fill_add_metadata']))

                # And add/claim the OSD
                AlbaController.add_osds(alba_backend_guid=slot_info['alba_backend_guid'],
                                        osds=[slot_info],
                                        alba_node_guid=node_guid,
                                        metadata=metadata)
        # Invalidate the stack and sync towards all passive sides
        active_node.invalidate_dynamics('stack')
        for node in node_cluster.alba_nodes:
            if node != active_node:
                try:
                    node.client.sync_stack(active_node.stack)
                except:
                    AlbaNodeClusterController._logger.exception('Error while syncing stacks to the passive side')
        node_cluster.invalidate_dynamics('stack')

    @staticmethod
    @ovs_task(name='albanodecluster.remove_slot', ensure_single_info={'mode': 'CHAINED'})
    def remove_slot(node_cluster_guid, node_guid, slot_id):
        """
        Removes a slot
        :param node_cluster_guid: Guid of the node cluster to remove a disk from
        :type node_cluster_guid: str
        :param node_guid: Guid of the AlbaNode to act as the 'active' side
        :type node_guid: basestring
        :param slot_id: Slot ID
        :type slot_id: str
        :return: None
        :rtype: NoneType
        """
        node_cluster = AlbaNodeCluster(node_cluster_guid)
        active_node = AlbaNode(node_guid)
        if active_node not in node_cluster.alba_nodes:
            raise ValueError('The requested active AlbaNode is not part of AlbaNodeCluster {0}'.format(node_cluster.guid))
        osds = [osd for osd in active_node.osds if osd.slot_id == slot_id]
        if len(osds) > 0:
            raise RuntimeError('A slot with claimed OSDs can\'t be removed')

        active_node.client.clear_slot(slot_id)
        active_node.invalidate_dynamics()
        # Invalidate the stack and sync towards all passive sides
        for node in node_cluster.alba_nodes:
            if node != active_node:
                try:
                    node.client.sync_stack(active_node.stack)
                except:
                    AlbaNodeClusterController._logger.exception('Error while syncing stacks to the passive side')
        if active_node.storagerouter is not None:
            DiskController.sync_with_reality(storagerouter_guid=active_node.storagerouter_guid)

    @staticmethod
    @ovs_task(name='albanodecluster.remove_osd', ensure_single_info={'mode': 'CHAINED'})
    def remove_osd(node_cluster_guid, node_guid, osd_id, expected_safety):
        """
        Removes an OSD
        :param node_cluster_guid: Guid of the AlbaNodeCluster
        :type node_cluster_guid: str
        :param node_guid: Guid of the node to remove an OSD from
        :type node_guid: str
        :param osd_id: ID of the OSD to remove
        :type osd_id: str
        :param expected_safety: Expected safety after having removed the OSD
        :type expected_safety: dict or None
        :return: Aliases of the disk on which the OSD was removed
        :rtype: list
        """
        node_cluster = AlbaNodeCluster(node_cluster_guid)
        active_node = AlbaNode(node_guid)
        if active_node not in node_cluster.alba_nodes:
            raise ValueError('The requested active AlbaNode is not part of AlbaNodeCluster {0}'.format(node_cluster.guid))
        # Retrieve corresponding OSD in model
        AlbaNodeClusterController._logger.debug('Removing OSD {0} at node {1}'.format(osd_id, active_node.ip))
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
        result = active_node.client.delete_osd(slot_id=osd.slot_id, osd_id=osd_id)
        if result['_success'] is False:
            raise RuntimeError('Error removing OSD: {0}'.format(result['_error']))
        # Invalidate the stack and sync towards all passive sides
        active_node.invalidate_dynamics('stack')
        for node in node_cluster.alba_nodes:
            if node != active_node:
                try:
                    node.client.sync_stack(active_node.stack)
                except:
                    AlbaNodeClusterController._logger.exception('Error while syncing stacks to the passive side')

        # Clean configuration management and model - Well, just try it at least
        if Configuration.exists(AlbaNodeClusterController.ASD_CONFIG.format(osd_id), raw=True):
            Configuration.delete(AlbaNodeClusterController.ASD_CONFIG_DIR.format(osd_id), raw=True)

        osd.delete()
        active_node.invalidate_dynamics()
        if alba_backend is not None:
            alba_backend.invalidate_dynamics()
            alba_backend.backend.invalidate_dynamics()
        if active_node.storagerouter is not None:
            try:
                DiskController.sync_with_reality(storagerouter_guid=active_node.storagerouter_guid)
            except UnableToConnectException:
                AlbaNodeClusterController._logger.warning('Skipping disk sync since StorageRouter {0} is offline'.format(active_node.storagerouter.name))

        return [osd.slot_id]

    @staticmethod
    @ovs_task(name='albanodecluster.reset_osd')
    def reset_osd(node_cluster_guid, node_guid, osd_id, expected_safety):
        """
        Removes and re-adds an OSD to a Disk
        :param node_cluster_guid: Guid of the AlbaNodeCluster
        :type node_cluster_guid: str
        :param node_guid: Guid of the node to reset an OSD of
        :type node_guid: str
        :param osd_id: OSD to reset
        :type osd_id: str
        :param expected_safety: Expected safety after having reset the disk
        :type expected_safety: dict
        :return: None
        :rtype: NoneType
        """
        node_cluster = AlbaNodeCluster(node_cluster_guid)
        active_node = AlbaNode(node_guid)
        if active_node not in node_cluster.alba_nodes:
            raise ValueError('The requested active AlbaNode is not part of AlbaNodeCluster {0}'.format(node_cluster.guid))
        osd = AlbaOSDList.get_by_osd_id(osd_id)
        fill_slot_extra = active_node.client.build_slot_params(osd)
        disk_aliases = AlbaNodeClusterController.remove_osd(node_guid=node_guid, osd_id=osd_id, expected_safety=expected_safety)
        if len(disk_aliases) == 0:
            return
        try:
            active_node.client.fill_slot(osd.slot_id, fill_slot_extra)
        except (requests.ConnectionError, requests.Timeout):
            AlbaNodeClusterController._logger.warning('Could not connect to node {0} to (re)configure ASD'.format(active_node.guid))
            return
        except NotFoundError:
            # Can occur when the slot id could not be matched with an existing slot on the alba-asd manager
            # This error can be anticipated when the status of the osd would be 'missing' in the nodes stack but that would be too much overhead
            message = 'Could not add a new OSD. The requested slot {0} could not be found'.format(osd.slot_id)
            AlbaNodeClusterController._logger.warning(message)
            raise RuntimeError('{0}. Slot {1} might no longer be present on Alba node {2}'.format(message, osd.slot_id, node_guid))
        # Invalidate the stack and sync towards all passive sides
        active_node.invalidate_dynamics('stack')
        for node in node_cluster.alba_nodes:
            if node != active_node:
                try:
                    node.client.sync_stack(active_node.stack)
                except:
                    AlbaNodeClusterController._logger.exception('Error while syncing stacks to the passive side')
