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
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.lib.albanodecontroller import AlbaNodeController
from ovs.lib.albacontroller import AlbaController
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
    def list(self, alba_backend_guid, discover=False):
        """
        Lists all available ALBA Nodes
        """
        if discover is False:
            nodes = AlbaNodeList.get_albanodes()
            all_osds = AlbaController.list_all_osds.delay(alba_backend_guid).get()
            for node in nodes:
                node.ips = AlbaNodeController.fetch_ips.delay(node_guid=node.guid).get()
                node.disks = [disk for disk in AlbaNodeController.fetch_disks.delay(node.guid).get().values()]
                for disk in node.disks:
                    if disk['available'] is True:
                        disk['status'] = 'uninitialized'
                    else:
                        if disk['state']['state'] == 'ok':
                            disk['status'] = 'initialized'
                            for osd in all_osds:
                                if osd['box_id'] == node.box_id and 'asd_id' in disk and osd['long_id'] == disk['asd_id']:
                                    if osd['id'] is None:
                                        if osd['alba_id'] is None:
                                            disk['status'] = 'available'
                                        else:
                                            disk['status'] = 'unavailable'
                                            other_abackend = AlbaBackendList.get_by_alba_id(osd['alba_id'])
                                            if other_abackend is not None:
                                                disk['status_detail'] = other_abackend.guid
                                    else:
                                        disk['status'] = 'claimed'
                        else:
                            disk['status'] = 'error'
                            disk['status_detail'] = disk['state']['detail']
            return nodes
        else:
            model_nodes = AlbaNodeList.get_albanodes()
            model_ips = [node.ip for node in model_nodes]
            nodes_data = AlbaNodeController.discover.delay().get()
            nodes = {}
            for node_data in nodes_data:
                node = AlbaNode(data=node_data, volatile=True)
                if node.ip not in model_ips:
                    node.ips = AlbaNodeController.fetch_ips.delay(ip=node.ip, port=node.port).get()
                    nodes[node.guid] = node
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
