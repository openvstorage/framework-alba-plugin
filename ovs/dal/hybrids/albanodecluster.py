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
AlbaNodeCluster module
"""

from ovs.dal.dataobject import DataObject
from ovs.dal.structures import Dynamic, Property
from ovs.extensions.generic.logger import Logger


class AlbaNodeCluster(DataObject):
    """
    The AlbaNodeCluster represents a group of AlbaNodes which will function as one
    The idea behind the cluster is that when one AlbaNode would fail, another can take over
    The information within the AlbaNodes would be the same (same stack information)
    This cluster contains the same information as an AlbaNode for representation purposes
    """
    CLUSTER_TYPES = DataObject.enumerator('ClusterType', ['ASD', 'GENERIC', 'MIXED'])

    _logger = Logger('hybrids')
    __properties = [Property('name', str, mandatory=False, doc='Optional name for the AlbaNode')]
    __dynamics = [Dynamic('type', CLUSTER_TYPES.keys(), 3600),
                  Dynamic('ips', list, 3600),
                  Dynamic('cluster_metadata', dict, 3600),
                  Dynamic('local_summary', dict, 60),
                  Dynamic('stack', dict, 15, locked=True),
                  Dynamic('maintenance_services', dict, 30, locked=True),
                  Dynamic('supported_osd_types', list, 3600),
                  Dynamic('read_only_mode', bool, 60)]

    def _type(self):
        """
        Retrieve the type of the cluster
        :return: Type of the cluster
        :rtype: str
        """
        node_type = None
        for alba_node in self.alba_nodes:
            if node_type is None:
                node_type = alba_node.type
                continue
            if alba_node.type != node_type:  # Should be blocked by the API. This type is currently not supported
                node_type = self.CLUSTER_TYPES.MIXED
                break
        return node_type

    def _cluster_metadata(self):
        """
        Returns a set of metadata hinting on how the cluster should be used
        The GUI/API can adapt based on this information
        """
        cluster_metadata = {'fill': False,  # Prepare Slot for future usage
                            'fill_add': False,  # OSDs will added and claimed right away
                            'clear': False}  # Indicates whether OSDs can be removed from ALBA Node / Slot
        if self.type == self.CLUSTER_TYPES.ASD:
            cluster_metadata.update({'fill': True,
                                     'fill_metadata': {'count': 'integer'},
                                     'clear': True})
        elif self.type == self.CLUSTER_TYPES.GENERIC:
            cluster_metadata.update({'fill_add': True,
                                     'fill_add_metadata': {'osd_type': 'osd_type',
                                                           'ips': 'list_of_ip',
                                                           'port': 'port'},
                                     'clear': True})
        # Do nothing in when the type is mixed as nothing is supported
        return cluster_metadata

    def _ips(self):
        """
        Returns the IPs of the nodes
        :return: List of lists with IPs of all linked Nodes
        :rtype: list[list[str]]
        """
        ips = []
        for alba_node in self.alba_nodes:
            ips.append(alba_node.ips)
        return ips

    def _maintenance_services(self):
        """
        Returns all maintenance services on this node, grouped by backend name
        """
        services = {}
        for alba_node in self.alba_nodes:
            services[alba_node.node_id] = alba_node.maintenance_services

    def _stack(self):
        """
        Returns an overview of this node's storage stack
        """
        stack = {}
        for alba_node in self.alba_nodes:
            stack[alba_node.node_id] = alba_node.stack
        # @Todo collapse information together based on active/passive
        # @todo Do not collapse on device both rother on slot id (which is an alias that should match)
        return stack

    def _supported_osd_types(self):
        """
        Returns a list of all supported OSD types
        """
        from ovs.dal.hybrids.albaosd import AlbaOSD
        if self.type == self.CLUSTER_TYPES.GENERIC:
            return [AlbaOSD.OSD_TYPES.ASD, AlbaOSD.OSD_TYPES.AD]
        if self.type == self.CLUSTER_TYPES.NODE_TYPES.ASD:
            return [AlbaOSD.OSD_TYPES.ASD]
        else:  # Mixed type
            return [AlbaOSD.OSD_TYPES.ASD, AlbaOSD.OSD_TYPES.AD]

    def _read_only_mode(self):
        """
        Indicates whether the ALBA Node can be used for OSD manipulation
        If the version on the ALBA Node is lower than a specific version required by the framework, the ALBA Node becomes read only,
        this means, that actions such as creating, restarting, deleting OSDs becomes impossible until the node's software has been updated
        :return: True if the ALBA Node should be read only, False otherwise
        :rtype: bool
        """
        # The whole cluster should be read-only as not all actions can be mirrored
        return any(alba_node.read_only_mode for alba_node in self.alba_nodes)

    def _local_summary(self):
        """
        Return a summary of the OSDs based on their state
        * Ok -> green
        * WARNING -> orange
        * ERROR -> red
        * UNKNOWN -> gray
        The summary will contain a list of dicts with guid, osd_id and claimed_by
        eg:
        {'red': [{osd_id: 1, claimed_by: alba_backend_guid1}],
         'green': [{osd_id: 2, claimed_by: None}],
          ...}
        :return: Summary of the OSDs filtered by status (which are represented by color)
        """
        local_summary = {}
        for alba_node in self.alba_nodes:
            local_summary[alba_node.node_id] = alba_node.local_summary
        return local_summary
