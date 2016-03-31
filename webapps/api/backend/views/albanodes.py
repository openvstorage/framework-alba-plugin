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
Contains the AlbaNodeViewSet
"""

from backend.decorators import load
from backend.decorators import log
from backend.decorators import required_roles
from backend.decorators import return_list
from backend.decorators import return_object
from backend.decorators import return_task
from ovs.dal.datalist import DataList
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.extensions.db.etcd.configuration import EtcdConfiguration
from ovs.lib.albanodecontroller import AlbaNodeController
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated


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
    def list(self, discover=False, ip=None, node_id=None):
        """
        Lists all available ALBA Nodes
        :param discover: If True and IP provided, return list of single ALBA node, If True and no IP provided, return all ALBA nodes else return modeled ALBA nodes
        :param ip: IP of ALBA node to retrieve
        :param node_id: ID of the ALBA node
        """
        if discover is False and (ip is not None or node_id is not None):
            raise RuntimeError('Discover is mutually exclusive with IP and nodeID')
        if (ip is None and node_id is not None) or (ip is not None and node_id is None):
            raise RuntimeError('Both IP and nodeID need to be specified')

        if discover is False:
            return AlbaNodeList.get_albanodes()

        if ip is not None:
            node = AlbaNode(volatile=True)
            node.ip = ip
            node.type = 'ASD'
            node.node_id = node_id
            node.port = EtcdConfiguration.get('/ovs/alba/asdnodes/{0}/config/main|port'.format(node_id))
            node.username = EtcdConfiguration.get('/ovs/alba/asdnodes/{0}/config/main|username'.format(node_id))
            node.password = EtcdConfiguration.get('/ovs/alba/asdnodes/{0}/config/main|password'.format(node_id))
            data = node.client.get_metadata()
            if data['_success'] is False and data['_error'] == 'Invalid credentials':
                raise RuntimeError('Invalid credentials')
            if data['node_id'] != node_id:
                raise RuntimeError('Unexpected node identifier. {0} vs {1}'.format(data['node_id'], node_id))
            node_list = DataList(AlbaNode, {})
            node_list._executed = True
            node_list._guids = [node.guid]
            node_list._objects = {node.guid: node}
            return node_list

        nodes = {}
        model_node_ids = [node.node_id for node in AlbaNodeList.get_albanodes()]
        found_node_ids = []
        asd_node_ids = []
        if EtcdConfiguration.dir_exists('/ovs/alba/asdnodes'):
            asd_node_ids = EtcdConfiguration.list('/ovs/alba/asdnodes')

        for node_id in asd_node_ids:
            node = AlbaNode(volatile=True)
            node.type = 'ASD'
            node.node_id = node_id
            node.ip = EtcdConfiguration.get('/ovs/alba/asdnodes/{0}/config/main|ip'.format(node_id))
            node.port = EtcdConfiguration.get('/ovs/alba/asdnodes/{0}/config/main|port'.format(node_id))
            node.username = EtcdConfiguration.get('/ovs/alba/asdnodes/{0}/config/main|username'.format(node_id))
            node.password = EtcdConfiguration.get('/ovs/alba/asdnodes/{0}/config/main|password'.format(node_id))
            if node.node_id not in model_node_ids and node.node_id not in found_node_ids:
                nodes[node.guid] = node
                found_node_ids.append(node.node_id)
        node_list = DataList(AlbaNode, {})
        node_list._executed = True
        node_list._guids = nodes.keys()
        node_list._objects = nodes
        return node_list

    @log()
    @required_roles(['read'])
    @return_object(AlbaNode)
    @load(AlbaNode)
    def retrieve(self, albanode):
        """
        Load information about a given AlbaBackend
        :param albanode: ALBA node to retrieve
        """
        return albanode

    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load()
    def create(self, node_id):
        """
        Adds a node with a given node_id to the model
        :param node_id: ID of the ALBA node to create
        """
        return AlbaNodeController.register.delay(node_id)

    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaNode)
    def initialize_disks(self, albanode, disks):
        """
        Initializes disks
        :param albanode: ALBA node to initialize disks
        :param disks: Disks to initialize
        """
        return AlbaNodeController.initialize_disks.delay(albanode.guid, disks)

    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaNode)
    def remove_disk(self, albanode, disk, alba_backend_guid, safety):
        """
        Removes a disk
        :param albanode: ALBA node to remove a disk from
        :param disk: Disk to remove
        :param alba_backend_guid: Guid of the ALBA backend
        :param safety: Safety to maintain
        """
        return AlbaNodeController.remove_disk.delay(alba_backend_guid, albanode.guid, disk, safety)

    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaNode)
    def restart_disk(self, albanode, disk):
        """
        Restarts a disk
        :param albanode: ALBA node to restart a disk from
        :param disk: Disk to restart
        """
        return AlbaNodeController.restart_disk.delay(albanode.guid, disk)
