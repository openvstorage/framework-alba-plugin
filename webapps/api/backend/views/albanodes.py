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
Contains the AlbaNodeViewSet
"""

from backend.decorators import required_roles, return_object, return_list, load, return_task, log
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.lib.albanodecontroller import AlbaNodeController
from ovs.dal.dataobjectlist import DataObjectList
from rest_framework import status
from rest_framework.response import Response


class AlbaNodeViewSet(viewsets.ViewSet):
    """
    Information about ALBA Nodes
    """
    permission_classes = (IsAuthenticated,)
    prefix = r'alba/nodes'
    base_name = 'albanodes'

    @log()
    @required_roles(['read'])
    @return_list(AlbaNode)
    @load()
    def list(self, discover=False, ip=None, port=None, username=None, password=None, node_id=None):
        """
        Lists all available ALBA Nodes
        """
        if discover is False:
            return AlbaNodeList.get_albanodes()
        elif ip is not None:
            node = AlbaNode(volatile=True)
            node.ip = ip
            node.port = int(port)
            node.username = username
            node.password = password
            data = node.client.get_metadata()
            if data['_success'] is False and data['_error'] == 'Invalid credentials':
                raise RuntimeError('Invalid credentials')
            if data['node_id'] != node_id:
                raise RuntimeError('Unexpected node identifier. {0} vs {1}'.format(data['node_id'], node_id))
            node_list = DataObjectList([node.guid], AlbaNode)
            node_list._objects = {node.guid: node}
            return node_list
        else:
            nodes = {}
            model_node_ids = [node.node_id for node in AlbaNodeList.get_albanodes()]
            found_node_ids = []
            for node_data in AlbaNodeController.discover.delay().get():
                node = AlbaNode(data=node_data, volatile=True)
                if node.node_id not in model_node_ids and node.node_id not in found_node_ids:
                    nodes[node.guid] = node
                    found_node_ids.append(node.node_id)
            node_list = DataObjectList(nodes.keys(), AlbaNode)
            node_list._objects = nodes
            return node_list

    @log()
    @required_roles(['read'])
    @return_object(AlbaNode)
    @load(AlbaNode)
    def retrieve(self, albanode):
        """
        Load information about a given AlbaBackend
        """
        return albanode

    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load()
    def create(self, node_id, ip, port, username, password, asd_ips):
        """
        Adds a node with a given node_id to the model
        """
        return AlbaNodeController.register.delay(node_id, ip, port, username, password, asd_ips)

    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaNode)
    def initialize_disks(self, albanode, disks):
        """
        Initializes disks
        """
        return AlbaNodeController.initialize_disks.delay(albanode.guid, disks)

    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaNode)
    def remove_disk(self, albanode, disk, alba_backend_guid, safety):
        """
        Removes a disk
        """
        return AlbaNodeController.remove_disk.delay(alba_backend_guid, albanode.guid, disk, safety)

    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaNode)
    def restart_disk(self, albanode, disk):
        """
        Restartes a disk
        """
        return AlbaNodeController.restart_disk.delay(albanode.guid, disk)
