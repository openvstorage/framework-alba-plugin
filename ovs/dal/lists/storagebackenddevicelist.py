# Copyright 2014 CloudFounders NV
# All rights reserved

"""
StorageBackendDeviceList module
"""
from ovs.dal.datalist import DataList
from ovs.dal.dataobject import DataObjectList
from ovs.dal.hybrids.storagebackenddevice import StorageBackendDevice


class StorageBackendDeviceList(object):
    """
    This StorageBackendDeviceList class contains various lists regarding to the StorageBackendDevice class
    """

    @staticmethod
    def get_devices():
        """
        Returns a list of all StorageBackendDevices
        """
        devices = DataList({'object': StorageBackendDevice,
                            'data': DataList.select.GUIDS,
                            'query': {'type': DataList.where_operator.AND,
                                      'items': []}}).data
        return DataObjectList(devices, StorageBackendDevice)

    @staticmethod
    def get_chassis():
        """
        Returns a list of all StorageBackendChassis
        """
        return True