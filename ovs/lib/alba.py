# Copyright 2014 CloudFounders NV
# All rights reserved

"""
AlbaController module
"""

from ovs.celery_run import celery
from ovs.log.logHandler import LogHandler
from ovs.lib.kineticdevice import KineticDeviceController
from ovs.dal.hybrids.kineticdevice import KineticDevice
from ovs.dal.hybrids.albabackend import AlbaBackend

logger = LogHandler('alba.lib', name='alba')


class AlbaController(object):
    """
    Contains all BLL related to ALBA
    """

    @staticmethod
    @celery.task(name='alba.alba.add_device')
    def add_device(alba_backend_guid, ip, port, serial):
        """
        Adds a device to the given ALBA backend
        """
        device = KineticDeviceController.get_device_info(ip, port)
        if device['configuration']['serialNumber'] != serial:
            raise RuntimeError('The Kinetic device has a different serial number')

        model_device = KineticDevice()
        model_device.alba_backend = AlbaBackend(alba_backend_guid)
        model_device.serial_number = serial
        model_device.connection_info = (ip, port)
        model_device.save()

        # @TODO: Actually do something like adding the device to the backend
