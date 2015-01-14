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
from subprocess import check_output
import json

logger = LogHandler('alba.lib', name='alba')


class AlbaController(object):
    """
    Contains all BLL related to ALBA
    """

    @staticmethod
    @celery.task(name='alba.add_device')
    def add_device(alba_backend_guid, serial, ip, port):
        """
        Adds a storage unit to an Alba backend
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

    @staticmethod
    @celery.task(name='alba.add_unit')
    def add_unit(alba_backend_guid, devices):
        """
        Adds a storage unit to an Alba backend
        """

        # @todo: backend name can be used to differentiate between different backend - abm combinations
        alba_backend = AlbaBackend(alba_backend_guid)

        for device in devices:
            cmd = """export LD_LIBRARY_PATH=/opt/alba/lib; """
            cmd += """/opt/alba/bin/alba add-osd --config /opt/alba/arakoon/cfg/alba.ini """
            cmd += """--host {0} --asd-port {1} --asd-id {2} --box-id {3}""".format(device['network_interfaces'][0]['ip_address'],
                                                                                    device['network_interfaces'][0]['port'],
                                                                                    device['serialNumber'],
                                                                                    device['configuration']['chassis'])
            output = check_output(cmd, shell=True).strip()
            logger.info('** abm response:' + str(output))

    @staticmethod
    @celery.task(name='alba.list_osds')
    def list_osds(alba_backend_guid):
        """
        list registered osds on local alba manager
        """
        alba_backend = AlbaBackend(alba_backend_guid)

        cmd = """export LD_LIBRARY_PATH=/opt/alba/lib; """
        cmd += """/opt/alba/bin/alba list-osds --config /opt/alba/arakoon/cfg/alba.ini --to-json 2>/dev/null """
        output = check_output(cmd, shell=True).strip()

        return json.loads(output)
