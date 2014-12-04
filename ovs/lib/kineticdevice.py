# Copyright 2014 CloudFounders NV
# All rights reserved

"""
KineticDeviceController module
"""

from ovs.celery_run import celery
from ovs.log.logHandler import LogHandler
from ovs.extensions.storage.volatilefactory import VolatileFactory
from ovs.extensions.generic.seagatekinetic import Kinetic

logger = LogHandler('alba.lib', name='kinetic')


class KineticDeviceController(object):
    """
    Contains all BLL related to Kinetic Devices
    """

    @staticmethod
    @celery.task(name='alba.kinetic.discover')
    def discover(interval=0, fresh=False):
        """
        Discovers kinetic devices.
        """
        key = 'ovs_kinetic_devices'
        volatile = VolatileFactory.get_client()
        data = volatile.get(key)
        if data is None or fresh is True:
            data = Kinetic.discover(interval=interval)
            volatile.set(key, data, 300)
        return data

    @staticmethod
    @celery.task(name='alba.get_device_info')
    def get_device_info(ip, port):
        """
        Loads information about a Kinetic device
        """
        return Kinetic.get_device_info(ip, port)
