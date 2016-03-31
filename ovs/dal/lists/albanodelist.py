# Copyright 2016 iNuron NV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
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
        if len(nodes) == 1:
            return nodes[0]
        return None
