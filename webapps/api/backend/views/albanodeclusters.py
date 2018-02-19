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

from rest_framework import viewsets
from rest_framework.decorators import action, link
from rest_framework.permissions import IsAuthenticated
from api.backend.decorators import load, log, required_roles, return_list, return_object, return_task
from ovs.dal.hybrids.albanodecluster import AlbaNodeCluster
from ovs.dal.lists.albanodeclusterlist import AlbaNodeClusterList
from ovs_extensions.api.exceptions import HttpNotAcceptableException
from ovs.lib.albanodecluster import AlbaNodeClusterController


class AlbaNodeViewSet(viewsets.ViewSet):
    """
    Information about ALBA Nodes
    """
    permission_classes = (IsAuthenticated,)
    prefix = r'alba/nodeclusters'
    base_name = 'albanodeclusters'
    return_exceptions = ['albanodes.create', 'albanodes.destroy']

    # noinspection PyProtectedMember
    @log()
    @required_roles(['read'])
    @return_list(AlbaNodeCluster)
    @load()
    def list(self):
        """
        Lists all available ALBA Nodes Clusters
        :return: A list of ALBA nodes Clusters
        :rtype: ovs.dal.datalist.DataList
        """
        return AlbaNodeClusterList.get_alba_node_clusters()

    @log()
    @required_roles(['read'])
    @return_object(AlbaNodeCluster)
    @load(AlbaNodeCluster)
    def retrieve(self, node_cluster):
        """
        Load information about a given AlbaBackend
        :param node_cluster: AlbaNodeCluster to retrieve
        :type node_cluster: ovs.dal.hybrids.albanodecluster.AlbaNodeCluster
        :return: The requested AlbaNodeCluster object
        :rtype: ovs.dal.hybrids.albanodecluster.AlbaNodeCluster
        """
        return node_cluster

    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load()
    def create(self, name):
        """
        Adds a node cluster with a given name to the model
        :param name: Name of the node cluster
        :type name: str
        :return: Celery async task result
        :rtype: CeleryTask
        """
        return AlbaNodeClusterController.create.delay(name)

    @log()
    @required_roles(['manage'])
    @return_task()
    @load(AlbaNodeCluster)
    def destroy(self, node_cluster):
        """
        Deletes an ALBA node
        :param node_cluster: The AlbaNodeCluster to be removed
        :type node_cluster: ovs.dal.hybrids.albanodecluster.AlbaNodeCluster
        :return: Celery async task result
        :rtype: CeleryTask
        """
        return AlbaNodeClusterController.remove_cluster.delay(node_cluster_guid=node_cluster.guid)

    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaNodeCluster)
    def fill_slots(self, node_cluster, slot_information, metadata=None):
        """
        Fills 1 or more Slots
        :param node_cluster: The AlbaNode on which the Slots will be filled
        :type node_cluster: ovs.dal.hybrids.albanodecluster.AlbaNodeCluster
        :param slot_information: A list of Slot information
        :type slot_information: list
        :param metadata: Extra metadata if required
        :type metadata: dict
        :return: Celery async task result
        :rtype: CeleryTask
        """
        return AlbaNodeClusterController.fill_slots.delay(node_cluster_guid=node_cluster.guid,
                                                          slot_information=slot_information,
                                                          metadata=metadata)

    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaNodeCluster)
    def remove_slot(self, node_cluster, slot):
        """
        Removes a disk
        :param node_cluster: AlbaNodeCluster to remove a disk from
        :type node_cluster: ovs.dal.hybrids.albanodecluster.AlbaNodeCluster
        :param slot: Slot to remove
        :type slot: str
        :return: Celery async task result
        :rtype: CeleryTask
        """
        return AlbaNodeClusterController.remove_slot.delay(node_cluster.guid, slot)

    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaNodeCluster)
    def reset_osd(self, node_cluster, osd_id, safety):
        """
        Removes and re-add an OSD
        :param node_cluster: AlbaNodeCluster to remove a disk from
        :type node_cluster: ovs.dal.hybrids.albanodecluster.AlbaNodeCluster
        :param osd_id: OSD ID to reset
        :type osd_id: str
        :param safety: Safety to maintain
        :type safety: dict
        :return: Celery async task result
        :rtype: CeleryTask
        """
        if safety is None:
            raise HttpNotAcceptableException(error='invalid_data',
                                             error_description='Safety must be passed')
        return AlbaNodeClusterController.reset_osd.delay(node_cluster.guid, osd_id, safety)

    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaNodeCluster)
    def restart_osd(self, node_cluster, osd_id):
        """
        Restarts an OSD process
        :param node_cluster: The node cluster on which the OSD runs
        :type node_cluster: ovs.dal.hybrids.albanodecluster.AlbaNodeCluster
        :param osd_id: The OSD to restart
        :type osd_id: str
        :return: Celery async task result
        :rtype: CeleryTask
        """
        return AlbaNodeClusterController.restart_osd.delay(node_cluster.guid, osd_id)
