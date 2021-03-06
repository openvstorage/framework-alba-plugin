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
Contains the AlbaNodeViewSet
"""
import re
from rest_framework import viewsets
from rest_framework.decorators import action, link
from rest_framework.permissions import IsAuthenticated
from api.backend.decorators import load, log, required_roles, return_list, return_object, return_simple, return_task
from ovs.dal.datalist import DataList
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs_extensions.api.exceptions import HttpNotAcceptableException
from ovs.lib.albanode import AlbaNodeController
from ovs.lib.albanodecluster import AlbaNodeClusterController
from ovs.lib.helpers.toolbox import Toolbox


class AlbaNodeViewSet(viewsets.ViewSet):
    """
    Information about ALBA Nodes
    """
    permission_classes = (IsAuthenticated,)
    prefix = r'alba/nodes'
    base_name = 'albanodes'
    return_exceptions = ['albanodes.create', 'albanodes.destroy']

    @classmethod
    def _discover_nodes(cls, ip=None, node_id=None):
        # type: (Optional[str], Optional[str]) -> Dict[str, AlbaNode]
        """
        :param ip: IP of ALBA node to retrieve
        :type ip: str
        :param node_id: ID of the ALBA node
        :type node_id: str
        :return: Dict with guid of the node mapped to the node itself
        :rtype: Dict[str, AlbaNode]
        """
        nodes = {}
        if ip is not None:
            # List the requested node
            node = AlbaNodeController.model_volatile_node(node_id, AlbaNode.NODE_TYPES.ASD, ip)
            data = node.client.get_metadata()
            if data['_success'] is False and data['_error'] == 'Invalid credentials':
                raise HttpNotAcceptableException(error='invalid_data',
                                                 error_description='Invalid credentials')
            if data['node_id'] != node_id:
                raise HttpNotAcceptableException(error='invalid_data',
                                                 error_description='Unexpected node identifier. {0} vs {1}'.format(
                                                     data['node_id'], node_id))
            nodes[node.guid] = node
        else:
            nodes.update(AlbaNodeController.discover_nodes())
        return nodes

    @log()
    @required_roles(['read'])
    @return_list(AlbaNode)
    @load()
    def list(self, discover=False, ip=None, node_id=None):
        """
        Lists all available ALBA Nodes
        :param discover: If True and IP provided, return list of single ALBA node, If True and no IP provided, return all ALBA nodes else return modeled ALBA nodes
        :type discover: bool
        :param ip: IP of ALBA node to retrieve
        :type ip: str
        :param node_id: ID of the ALBA node
        :type node_id: str
        :return: A list of ALBA nodes
        :rtype: ovs.dal.datalist.DataList
        """
        if discover is False and (ip is not None or node_id is not None):
            raise HttpNotAcceptableException(error='invalid_data',
                                             error_description='Discover is mutually exclusive with IP and nodeID')
        if (ip is None and node_id is not None) or (ip is not None and node_id is None):
            raise HttpNotAcceptableException(error='invalid_data',
                                             error_description='Both IP and nodeID need to be specified')

        if discover is False:
            return AlbaNodeList.get_albanodes()

        # Discover nodes
        nodes = self._discover_nodes(ip=ip, node_id=node_id)
        # Build the DataList
        node_list = DataList(AlbaNode)
        node_list._executed = True
        node_list._guids = nodes.keys()
        node_list._objects = nodes
        node_list._data = dict([(node.guid, {'guid': node.guid, 'data': node._data}) for node in nodes.values()])
        return node_list

    @log()
    @required_roles(['read'])
    @return_object(AlbaNode)
    @load(AlbaNode)
    def retrieve(self, albanode):
        """
        Load information about a given AlbaBackend
        :param albanode: ALBA node to retrieve
        :type albanode: ovs.dal.hybrids.albanode.AlbaNode
        :return: The requested AlbaNode object
        :rtype: ovs.dal.hybrids.albanode.AlbaNode
        """
        return albanode

    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load()
    def create(self, version, node_id=None, node_type=None, name=None):
        """
        Adds a node with a given node_id to the model
        :param version: Version of the client making the request
        :type version: int
        :param node_id: ID of the ALBA node to create
        :type node_id: str
        :param node_type: Type of the ALBA node to create
        :type node_type: str
        :param name: Name of the node (optional)
        :type name: str
        :return: Celery async task result
        :rtype: CeleryTask
        """
        if version >= 9:
            if name is not None and not re.match(Toolbox.regex_preset, name):
                raise HttpNotAcceptableException(error='invalid_data',
                                                 error_description='Invalid name specified. Minimum 3, maximum 20 alpha-numeric characters, dashes and underscores')
        if node_id is None and node_type != AlbaNode.NODE_TYPES.GENERIC:
            raise HttpNotAcceptableException(error='invalid_data',
                                             error_description='Field node_id is mandatory for node_type != GENERIC')
        return AlbaNodeController.register.delay(node_id, node_type, name)

    @log()
    @action()
    @required_roles(['manage'])
    @return_task()
    @load(AlbaNode)
    def replace_node(self, albanode, new_node_id):
        """
        Replace an existing Alba node with a newly configured node (only possible if IPs are identical)
        :param albanode: Guid of the ALBA node that needs to be replaced
        :type albanode: ovs.dal.hybrids.albanode.AlbaNode
        :param new_node_id: ID of the new ALBA node
        :type new_node_id: str
        :return: Celery async task result
        :rtype: CeleryTask
        """
        return AlbaNodeController.replace_node.delay(old_node_guid=albanode.guid, new_node_id=new_node_id)

    @log()
    @required_roles(['manage'])
    @return_task()
    @load(AlbaNode)
    def destroy(self, albanode):
        """
        Deletes an ALBA node
        :param albanode: The AlbaNode to be removed
        :type albanode: ovs.dal.hybrids.albanode.AlbaNode
        :return: Celery async task result
        :rtype: CeleryTask
        """
        return AlbaNodeController.remove_node.delay(node_guid=albanode.guid)

    @log()
    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_simple()
    @load(AlbaNode)
    def generate_empty_slot(self, albanode):
        """
        Generates an empty slot on the Alba Node
        :param albanode: The AlbaNode to generate a slot on
        :type albanode: ovs.dal.hybrids.albanode.AlbaNode
        :return: slot information
        :rtype: dict
        """
        return AlbaNodeController.generate_empty_slot(albanode.guid)

    @log()
    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaNode)
    def fill_slots(self, albanode, slot_information=None, osd_information=None, metadata=None):
        # type: (AlbaNode, Optional[List[dict]], Optional[List[dict]], Optional[dict]) -> any
        """
        Fills 1 or more Slots
        :param albanode: The AlbaNode on which the Slots will be filled
        :type albanode: ovs.dal.hybrids.albanode.AlbaNode
        :param slot_information: A list of OSD information. The name was chosen poorly and it was rectified
        :type slot_information: list
        :param osd_information: A list of OSD information. The name was chosen poorly and it was rectified
        :type osd_information: list
        :param metadata: Extra metadata if required
        :type metadata: dict
        :return: Celery async task result
        :rtype: CeleryTask
        """
        if all(param is None for param in [slot_information, osd_information]):
            raise ValueError('Either slot_information or osd_information should be passed.')
        osd_information = slot_information or osd_information
        if albanode.alba_node_cluster is not None:
            # The current node is treated as the 'active' side
            return AlbaNodeClusterController.fill_slots.delay(node_cluster_guid=albanode.alba_node_cluster.guid,
                                                              node_guid=albanode.guid,
                                                              osd_information=osd_information,
                                                              metadata=metadata)
        return AlbaNodeController.fill_slots.delay(node_guid=albanode.guid,
                                                   osd_information=osd_information,
                                                   metadata=metadata)

    @log()
    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaNode, max_version=8)
    def initialize_disks(self, albanode, disks):
        """
        Initializes disks
        DEPRECATED API call - use fill_slot in the future
        :param albanode: ALBA node to initialize disks
        :type albanode: ovs.dal.hybrids.albanode.AlbaNode
        :param disks: Disks to initialize (dict from type {disk_alias (str): amount of asds (int)})
        :type disks: dict
        :return: Celery async task result
        :rtype: CeleryTask
        """
        # Currently backwards compatible, should be removed at some point
        # Map to fill_slot for backwards compatibility
        # Old call example:
        # Data: {disks: {/dev/disk/by-id/ata-QEMU_HARDDISK_7f8acdce-979d-11e6-b: 2}}
        # New call example:
        # Data: [{alba_backend_guid: "0d3829bb-98fb-4ead-8772-862f37fb45dd", count:1, osd_type:"ASD", slot_id:"ata-QEMU_HARDDISK_1a078cce-511c-11e7-8"}]
        # Alba backend guid can be ignored for just filling slots
        osd_type = 'ASD'  # Always for this backwards compatible call
        osd_information = []
        for disk_alias, count in disks.iteritems():
            slot_id = disk_alias.split('/')[-1]
            osd_information.append({'slot_id': slot_id,
                                     'count': count,
                                     'osd_type': osd_type})
        return AlbaNodeController.fill_slots.delay(node_guid=albanode.guid, osd_information=osd_information)

    @log()
    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaNode, max_version=8)
    def remove_disk(self, albanode, disk):
        """
        Removes a disk
        DEPRECATED API call - Use 'remove_slot' instead
        :param albanode: ALBA node to remove a disk from
        :type albanode: ovs.dal.hybrids.albanode.AlbaNode
        :param disk: Disk to remove
        :type disk: str
        :return: Celery async task result
        :rtype: CeleryTask
        """
        # Currently backwards compatible, should be removed at some point
        slot_id = disk.split('/')[-1]
        return AlbaNodeController.remove_slot.delay(albanode.guid, slot_id)  # Giving a disk alias a try

    @log()
    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaNode)
    def remove_slot(self, albanode, slot):
        """
        Removes a disk
        :param albanode: ALBA node to remove a disk from
        :type albanode: ovs.dal.hybrids.albanode.AlbaNode
        :param slot: Slot to remove
        :type slot: str
        :return: Celery async task result
        :rtype: CeleryTask
        """
        if albanode.alba_node_cluster is not None:
            # The current node is treated as the 'active' side
            return AlbaNodeClusterController.remove_slot.delay(node_cluster_guid=albanode.alba_node_cluster.guid,
                                                               node_guid=albanode.guid,
                                                               slot_id=slot)
        return AlbaNodeController.remove_slot.delay(albanode.guid, slot)

    @log()
    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaNode, max_version=8)
    def reset_asd(self, albanode, asd_id, safety):
        """
        Removes and re-add an ASD
        DEPRECATED API call - Use 'reset_osd' instead
        :param albanode: ALBA node to remove a disk from
        :type albanode: ovs.dal.hybrids.albanode.AlbaNode
        :param asd_id: ASD ID to reset
        :type asd_id: str
        :param safety: Safety to maintain
        :type safety: dict
        :return: Celery async task result
        :rtype: CeleryTask
        """
        if safety is None:
            raise HttpNotAcceptableException(error='invalid_data',
                                             error_description='Safety must be passed')
        return AlbaNodeController.reset_osd.delay(albanode.guid, asd_id, safety)

    @log()
    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaNode)
    def reset_osd(self, albanode, osd_id, safety):
        """
        Removes and re-add an OSD
        :param albanode: ALBA node to remove a disk from
        :type albanode: ovs.dal.hybrids.albanode.AlbaNode
        :param osd_id: OSD ID to reset
        :type osd_id: str
        :param safety: Safety to maintain
        :type safety: dict
        :return: Celery async task result
        :rtype: CeleryTask
        """
        if safety is None:
            raise HttpNotAcceptableException(error='invalid_data',
                                             error_description='Safety must be passed')
        if albanode.alba_node_cluster is not None:
            # The current node is treated as the 'active' side
            return AlbaNodeClusterController.reset_osd.delay(node_cluster_guid=albanode.alba_node_cluster.guid,
                                                             node_guid=albanode.guid,
                                                             osd_id=osd_id,
                                                             safety=safety)
        return AlbaNodeController.reset_osd.delay(albanode.guid, osd_id, safety)

    @log()
    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaNode, max_version=8)
    def restart_asd(self, albanode, asd_id):
        """
        Restarts an ASD process
        DEPRECATED API call - Use 'restart_osd' instead
        :param albanode: The node on which the ASD runs
        :type albanode: ovs.dal.hybrids.albanode.AlbaNode
        :param asd_id: The ASD to restart
        :type asd_id: str
        :return: Celery async task result
        :rtype: CeleryTask
        """
        # Currently backwards compatible, should be removed at some point
        return AlbaNodeController.restart_osd.delay(albanode.guid, osd_id=asd_id)

    @log()
    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaNode)
    def restart_osd(self, albanode, osd_id):
        """
        Restarts an OSD process
        :param albanode: The node on which the OSD runs
        :type albanode: ovs.dal.hybrids.albanode.AlbaNode
        :param osd_id: The OSD to restart
        :type osd_id: str
        :return: Celery async task result
        :rtype: CeleryTask
        """
        # Changes nothing for the Dual Controller implementation. The 'Active side' will restart the OSD
        return AlbaNodeController.restart_osd.delay(albanode.guid, osd_id)

    @log()
    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaNode, max_version=8)
    def restart_disk(self, albanode, disk):
        """
        Restarts a disk
        DEPRECATED API call
        :param albanode: ALBA node to restart a disk from
        :type albanode: ovs.dal.hybrids.albanode.AlbaNode
        :param disk: Disk to restart
        :type disk: str
        :return: Celery async task result
        :rtype: CeleryTask
        """
        # Currently backwards compatible, should be removed at some point
        slot_id = disk.split('/')[-1]
        return AlbaNodeController.restart_slot.delay(albanode.guid, slot_id)

    @log()
    @link()
    @required_roles(['read', 'manage'])
    @return_task()
    @load(AlbaNode)
    def get_logfiles(self, albanode, local_storagerouter):
        """
        Retrieve the log files of an ALBA node
        :param albanode: ALBA node to restart a disk from
        :type albanode: ovs.dal.hybrids.albanode.AlbaNode
        :param local_storagerouter: The StorageRouter on which the call was initiated and on which the logs will end up
        :type local_storagerouter: ovs.dal.hybrids.storagerouter.StorageRouter
        :return: Celery async task result
        :rtype: CeleryTask
        """
        return AlbaNodeController.get_logfiles.delay(albanode_guid=albanode.guid, local_storagerouter_guid=local_storagerouter.guid)
