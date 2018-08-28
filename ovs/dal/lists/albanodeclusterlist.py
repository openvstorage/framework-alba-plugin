# Copyright (C) 2018 iNuron NV
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
AlbaBackendList module
"""
from ovs.dal.datalist import DataList
from ovs.dal.hybrids.albanodecluster import AlbaNodeCluster


class AlbaNodeClusterList(object):
    """
    This AlbaBackendList class contains various lists regarding to the AlbaBackend class
    """

    @staticmethod
    def get_alba_node_clusters():
        """
        Returns a list of all ALBABackends
        :rtype: DataList[ovs.dal.hybrids.albanodecluster.AlbaNodeCluster]
        """
        return DataList(AlbaNodeCluster, {'type': DataList.where_operator.AND, 'items': []})

    @staticmethod
    def get_by_name(name):
        """
        Gets an AlbaBackend by the alba_id
        :rtype: DataList[ovs.dal.hybrids.albanodecluster.AlbaNodeCluster]
        """
        backends = DataList(AlbaNodeCluster, {'type': DataList.where_operator.AND,
                                              'items': [('name', DataList.operator.EQUALS, name)]})
        if len(backends) > 1:
            raise RuntimeError('Multiple AlbaNodeCLusters found with name {0}'.format(name))
        if len(backends) == 1:
            return backends[0]
        return None
