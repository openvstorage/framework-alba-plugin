# Copyright 2014 CloudFounders NV
# All rights reserved

"""
KineticDevice module
"""
from ovs.dal.dataobject import DataObject
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.structures import Property, Relation


class KineticDevice(DataObject):
    """
    The KineticDevice represents a Seagate Kinetic device (either a Kinetic drive or a simulator)
    """
    __properties = [Property('identifier', str, doc='Kinetic Device identifier')]
    __relations = [Relation('alba_backend', AlbaBackend, 'kinetics', doc='ALBA backend using the devices')]
    __dynamics = []
