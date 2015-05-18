# Copyright 2015 CloudFounders NV
# All rights reserved

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
    def list(self, discover=False):
        """
        Lists all available ALBA Nodes
        """
        if discover is False:
            return AlbaNodeList.get_albanodes()
        else:
            nodes = {}
            model_box_ids = [node.box_id for node in AlbaNodeList.get_albanodes()]
            found_box_ids = []
            for node_data in AlbaNodeController.discover.delay().get():
                node = AlbaNode(data=node_data, volatile=True)
                if node.box_id not in model_box_ids and node.box_id not in found_box_ids:
                    nodes[node.guid] = node
                    found_box_ids.append(node.box_id)
            node_list = DataObjectList(nodes.keys(), AlbaNode)
            node_list._objects = nodes
            return node_list

    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load()
    def create(self, box_id, ip, port, username, password, asd_ips):
        """
        Adds a node with a given box_id to the model
        """
        return AlbaNodeController.register.delay(box_id, ip, port, username, password, asd_ips)

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
    def remove_disk(self, albanode, disk, alba_backend_guid):
        """
        Removes a disk
        """
        return AlbaNodeController.remove_disk.delay(alba_backend_guid, albanode.guid, disk)

    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaNode)
    def restart_disk(self, albanode, disk):
        """
        Restartes a disk
        """
        return AlbaNodeController.restart_disk.delay(albanode.guid, disk)
