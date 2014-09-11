# Copyright 2014 CloudFounders NV
# All rights reserved

"""
Contains the KineticDeviceViewSet
"""

from backend.decorators import required_roles, return_object, return_list, load
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from ovs.dal.hybrids.kineticdevice import KineticDevice
from ovs.dal.lists.kineticdevicelist import KineticDeviceList


class KineticDeviceViewSet(viewsets.ViewSet):
    """
    Information about KineticDevices
    """
    permission_classes = (IsAuthenticated,)
    prefix = r'alba/kineticdevices'
    base_name = 'kineticdevices'

    @required_roles(['read'])
    @return_list(KineticDevice)
    @load()
    def list(self):
        """
        Lists all available KineticDevices
        """
        return KineticDeviceList.get_devices()

    @required_roles(['read'])
    @return_object(KineticDevice)
    @load(KineticDevice)
    def retrieve(self, kineticdevice):
        """
        Load information about a given KineticDevice
        """
        return kineticdevice
