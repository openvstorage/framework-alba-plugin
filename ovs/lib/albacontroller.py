# Copyright 2014 CloudFounders NV
# All rights reserved

"""
AlbaController module
"""

from ovs.celery_run import celery
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.lists.servicelist import ServiceList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs.extensions.db.arakoon.ArakoonInstaller import ArakoonInstaller
from ovs.lib.setup import System
from ovs.log.logHandler import LogHandler

from ovs.dal.hybrids.j_nsmservice import NSMService
from ovs.dal.hybrids.j_abmservice import ABMService
from ovs.dal.hybrids.service import Service
from ovs.dal.lists.servicetypelist import ServiceTypeList

from subprocess import check_output
import json

logger = LogHandler('alba.lib', name='alba')


class AlbaController(object):
    """
    Contains all BLL related to ALBA
    """
    @staticmethod
    @celery.task(name='alba.add_unit')
    def add_unit(alba_backend_guid, devices):
        """
        Adds a storage unit to an Alba backend
        """
        # @todo: backend name can be used to differentiate between different backend - abm combinations
        alba_backend = AlbaBackend(alba_backend_guid)
        config_file = '/opt/OpenvStorage/config/arakoon/{0}/{0}.cfg'.format(alba_backend.backend.name + '-abm')

        for device in devices:
            cmd = """export LD_LIBRARY_PATH=/opt/alba/lib; """
            cmd += """/opt/alba/bin/alba add-osd --config {0} """.format(config_file)
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
        config_file = '/opt/OpenvStorage/config/arakoon/{0}/{0}.cfg'.format(alba_backend.backend.name + '-abm')

        cmd = """export LD_LIBRARY_PATH=/opt/alba/lib; """
        cmd += """/opt/alba/bin/alba list-osds --config {0} --to-json 2>/dev/null """.format(config_file)
        output = check_output(cmd, shell=True).strip()

        return json.loads(output)

    @staticmethod
    @celery.task(name='alba.add_cluster')
    def add_cluster(alba_backend_guid, ip, base_dir=None, client_start_port=None, messaging_start_port=None):
        """
        Adds an arakoon cluster to service backend
        """
        nsmservice_type = ServiceTypeList.get_by_name('NamespaceManager')
        abmservice_type = ServiceTypeList.get_by_name('AlbaManager')

        ovs_config = System.read_ovs_config()
        if base_dir is None:
            base_dir = ovs_config.get('arakoon', 'base.dir')
        if client_start_port is None:
            client_start_port = ovs_config.get('arakoon', 'client.port')
        if messaging_start_port is None:
            messaging_start_port = ovs_config.get('arakoon', 'messaging.port')

        albabackend = AlbaBackend(alba_backend_guid)
        abm_name = albabackend.backend.name + "-abm"
        nsm_name = albabackend.backend.name + "-nsm_0"

        ports_to_exclude = ServiceList.get_service_ports_in_use()
        result = ArakoonInstaller.create_cluster(abm_name, ip, base_dir, client_start_port, messaging_start_port,
                                                 ports_to_exclude, ArakoonInstaller.ABM_PLUGIN)
        service = Service()
        service.name = abm_name
        service.type = abmservice_type
        service.ports = [result['client_port'], result['messaging_port']]
        service.storagerouter = StorageRouterList.get_by_ip(ip)
        service.save()
        abm_service = ABMService()
        abm_service.service = service
        abm_service.alba_backend = albabackend
        abm_service.save()
        ArakoonInstaller.start(abm_name, ip)

        ports_to_exclude = ServiceList.get_service_ports_in_use()
        result = ArakoonInstaller.create_cluster(nsm_name, ip, base_dir, client_start_port, messaging_start_port,
                                                 ports_to_exclude, ArakoonInstaller.NSM_PLUGIN)
        service = Service()
        service.name = nsm_name
        service.type = nsmservice_type
        service.ports = [result['client_port'], result['messaging_port']]
        service.storagerouter = StorageRouterList.get_by_ip(ip)
        service.save()
        nsm_service = NSMService()
        nsm_service.service = service
        nsm_service.alba_backend = albabackend
        nsm_service.number = 0
        nsm_service.save()
        ArakoonInstaller.start(nsm_name, ip)
        ArakoonInstaller.register_nsm(abm_name, nsm_name, ip)

        albabackend.backend.status = 'RUNNING'
        albabackend.backend.save()

    @staticmethod
    @celery.task(name='alba.extend_cluster')
    def extend_cluster(cluster_name, source_ip):
        """
        Extends an arakoon cluster to local host based on existing config on source ip
        """
        # @todo: to be implemented
        pass

    @staticmethod
    @celery.task(name='alba.get_config_metadata')
    def get_config_metadata(alba_backend_guid):
        """
        Gets the configuration metadata for an Alba backend
        """
        backend = AlbaBackend(alba_backend_guid)
        config = ArakoonInstaller.get_client_config_from(backend.abm_service.service.storagerouter.ip,
                                                         backend.abm_service.service.name)
        config_dict = {}
        for section in config.sections():
            config_dict[section] = dict(config.items(section))
        return config_dict
