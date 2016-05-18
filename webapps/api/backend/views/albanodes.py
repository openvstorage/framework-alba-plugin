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
            node_list._data = {node.guid: {'guid': node.guid, 'data': node._data}}
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
    def remove_disk(self, albanode, disk):
        """
        Removes a disk
        :param albanode: ALBA node to remove a disk from
        :param disk: Disk to remove
        """
        return AlbaNodeController.remove_disk.delay(albanode.guid, disk)

    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaNode)
    def reset_asd(self, albanode, asd_id, safety):
        """
        Removes and re-add an ASD
        :param albanode: ALBA node to remove a disk from
        :param asd_id: ASDID to be resetted
        :param safety: Safety to maintain
        """
        return AlbaNodeController.reset_asd.delay(albanode.guid, asd_id, safety)

    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaNode)
    def restart_asd(self, albanode, asd_id):
        """
        Restarts an ASD process
        :param albanode: The node on which the ASD runs
        :param asd_id: The ASD to restart
        """
        return AlbaNodeController.restart_asd.delay(albanode.guid, asd_id)

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
