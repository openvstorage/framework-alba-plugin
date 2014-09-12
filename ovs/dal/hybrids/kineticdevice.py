# Copyright 2014 CloudFounders NV
# All rights reserved

"""
KineticDevice module
"""
from ovs.dal.dataobject import DataObject
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.structures import Property, Relation, Dynamic
from ovs.extensions.generic.seagatekinetic import Kinetic


class KineticDevice(DataObject):
    """
    The KineticDevice represents a Seagate Kinetic device (either a Kinetic drive or a simulator)
    """
    __properties = [Property('serial_number', str, doc='Kinetic Device serial number'),
                    Property('connection_info', tuple, doc='Contains information regarding connectivity')]
    __relations = [Relation('alba_backend', AlbaBackend, 'kinetics', doc='ALBA backend using the devices')]
    __dynamics = [Dynamic('capacity', int, 3600),
                  Dynamic('network_interfaces', list, 3600),
                  Dynamic('percent_free', float, 300)]

    def _capacity(self):
        """
        Loads the capacity of this device.
        """
        live_device = Kinetic.get_device_info(self.connection_info[0], self.connection_info[1])
        return live_device['capacity']['nominal']

    def _network_interfaces(self):
        """
        Returns the live network interfaces.
        """
        live_device = Kinetic.get_device_info(self.connection_info[0], self.connection_info[1])
        return live_device['network_interfaces']

    def _percent_free(self):
        """
        Loads the free space of this device.
        """
        live_device = Kinetic.get_device_info(self.connection_info[0], self.connection_info[1])
        return live_device['capacity']['percent_empty']
