# Copyright 2014 CloudFounders NV
# All rights reserved

"""
AlbaBackend module
"""
from ovs.dal.dataobject import DataObject
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.structures import Property, Relation, Dynamic


class AlbaASD(DataObject):
    """
    The AlbaASD represents a claimed ASD
    """
    __properties = [Property('asd_id', str, doc='ASD identifier')]
    __relations = [Relation('alba_backend', AlbaBackend, 'asds', doc='The AlbaBackend that claimed the ASD'),
                   Relation('alba_node', AlbaNode, 'asds', doc='The AlbaNode to which the ASD belongs')]
    __dynamics = [Dynamic('name', str, 3600),
                  Dynamic('info', dict, 5)]

    def _name(self):
        """
        Returns the name based on the asd_id
        """
        return self.asd_id[-6]

    def _info(self):
        """
        Returns the ASD information from its node
        """
        for disk in self.alba_node.all_disks:
            if disk['name'] == self.name:
                return disk
