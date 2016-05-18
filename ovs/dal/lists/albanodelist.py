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
AlbaNodeList module
"""
from ovs.dal.datalist import DataList
from ovs.dal.hybrids.albanode import AlbaNode


class AlbaNodeList(object):
    """
    This AlbaNodeList class contains various lists regarding to the AlbaNode class
    """

    @staticmethod
    def get_albanodes():
        """
        Returns a list of all AlbaNodes
        """
        return DataList(AlbaNode, {'type': DataList.where_operator.AND,
                                   'items': []})

    @staticmethod
    def get_albanode_by_ip(ip):
        """
        Returns a node by IP
        :param ip: IP of the ALBa node to retrieve
        """
        nodes = DataList(AlbaNode, {'type': DataList.where_operator.AND,
                                    'items': [('ip', DataList.operator.EQUALS, ip)]})
        if len(nodes) > 1:
            raise RuntimeError('Multiple ALBA Nodes found with ip {0}'.format(ip))
        if len(nodes) == 1:
            return nodes[0]
        return None

    @staticmethod
    def get_albanode_by_node_id(node_id):
        """
        Returns a node by its node_id
        :param node_id: ID of the ALBA node to retrieve
        """
        nodes = DataList(AlbaNode, {'type': DataList.where_operator.AND,
                                    'items': [('node_id', DataList.operator.EQUALS, node_id)]})
        if len(nodes) > 1:
            raise RuntimeError('Multiple ALBA Nodes found with node_id {0}'.format(node_id))
        if len(nodes) == 1:
            return nodes[0]
        return None
