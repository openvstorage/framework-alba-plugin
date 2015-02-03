# Copyright 2014 CloudFounders NV
# All rights reserved

"""
AlbaController module
"""

from ovs.celery_run import celery
from ovs.dal.hybrids.kineticdevice import KineticDevice
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.extensions.db.arakoon.ArakoonInstaller import ArakoonInstaller
from ovs.lib.setup import System
from ovs.log.logHandler import LogHandler

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
        # @TODO: Try to validate whether the ip and port are matching the given serial (maybe ask the AM?)

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

    @staticmethod
    @celery.task(name='alba.add_cluster')
    def add_cluster(cluster_name, ip, base_dir=None, client_port=None, messaging_port=None):
        """
        Adds an arakoon cluster to service backend
        """
        # @todo: parameters should be dynamically retrieved from modelled Service(s)

        ovs_config = System.read_ovs_config()
        if base_dir is None:
            base_dir = ovs_config.get('arakoon', 'base.dir')
        if client_port is None:
            client_port = ovs_config.get('arakoon', 'client.port')
        if messaging_port is None:
            messaging_port = ovs_config.get('arakoon', 'messaging.port')

        alba_manager = cluster_name + "-abm_0"
        namespace_manager = cluster_name + "-nsm_0"

        ArakoonInstaller.create_cluster(base_dir, alba_manager, ip, client_port, messaging_port, ArakoonInstaller.ABM_PLUGIN)
        ArakoonInstaller.create_cluster(base_dir, namespace_manager, ip, client_port, messaging_port, ArakoonInstaller.NSM_PLUGIN)

    @staticmethod
    @celery.task(name='alba.extend_cluster')
    def extend_cluster(cluster_name, source_ip):
        """
        Extends an arakoon cluster to local host based on existing config on source ip
        """
        # @todo: to be implemented
        pass
