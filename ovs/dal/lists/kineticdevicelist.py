# Copyright 2014 CloudFounders NV
# All rights reserved

"""
KineticDeviceList module
"""
from ovs.dal.datalist import DataList
from ovs.dal.dataobject import DataObjectList
from ovs.dal.hybrids.kineticdevice import KineticDevice


class KineticDeviceList(object):
    """
    This KineticDeviceList class contains various lists regarding to the KineticDevice class
    """

    @staticmethod
    def get_devices():
        """
        Returns a list of all KineticDevices
        """
        devices = DataList({'object': KineticDevice,
                            'data': DataList.select.GUIDS,
                            'query': {'type': DataList.where_operator.AND,
                                      'items': []}}).data
        return DataObjectList(devices, KineticDevice)
