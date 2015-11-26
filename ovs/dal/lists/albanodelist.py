# Copyright 2014 iNuron NV
#
# Licensed under the Open vStorage Modified Apache License (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.openvstorage.org/license
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
AlbaNodeList module
"""
from ovs.dal.datalist import DataList
from ovs.dal.dataobject import DataObjectList
from ovs.dal.helpers import Descriptor
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
        nodes = DataList({'object': AlbaNode,
                          'data': DataList.select.GUIDS,
                          'query': {'type': DataList.where_operator.AND,
                                    'items': []}}).data
        return DataObjectList(nodes, AlbaNode)

    @staticmethod
    def get_albanode_by_ip(ip):
        """
        Returns a node by ip
        """
        nodes = DataList({'object': AlbaNode,
                          'data': DataList.select.GUIDS,
                          'query': {'type': DataList.where_operator.AND,
                                    'items': [('ip', DataList.operator.EQUALS, ip)]}}).data
        if len(nodes) == 1:
            return Descriptor(AlbaNode, nodes[0]).get_object(True)
        return None

    @staticmethod
    def get_albanode_by_node_id(node_id):
        """
        Returns a node by its node_id
        """
        nodes = DataList({'object': AlbaNode,
                          'data': DataList.select.GUIDS,
                          'query': {'type': DataList.where_operator.AND,
                                    'items': [('node_id', DataList.operator.EQUALS, node_id)]}}).data
        if len(nodes) == 1:
            return Descriptor(AlbaNode, nodes[0]).get_object(True)
        return None
