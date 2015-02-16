# Copyright 2014 CloudFounders NV
# All rights reserved

"""
AlbaController module
"""

from ovs.celery_run import celery
from celery.schedules import crontab
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.lists.servicelist import ServiceList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs.extensions.db.arakoon.ArakoonInstaller import ArakoonInstaller
from ovs.extensions.alba.albacli import AlbaCLI
from ovs.extensions.generic.sshclient import SSHClient
from ovs.plugin.provider.configuration import Configuration
from ovs.lib.setup import System
from ovs.lib.helpers.decorators import ensure_single, setup_hook
from ovs.log.logHandler import LogHandler

from ovs.dal.hybrids.j_nsmservice import NSMService
from ovs.dal.hybrids.j_abmservice import ABMService
from ovs.dal.hybrids.service import Service
from ovs.dal.lists.servicetypelist import ServiceTypeList
from ovs.dal.lists.albabackendlist import AlbaBackendList

from subprocess import check_output
import json

logger = LogHandler('lib', name='alba')


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
            cmd = """export LD_LIBRARY_PATH=/usr/lib/alba; """
            cmd += """/usr/bin/alba add-osd --config {0} """.format(config_file)
            cmd += """--host {0} --asd-port {1} --box-id {2}""".format(device['network_interfaces'][0]['ip_address'],
                                                                       device['network_interfaces'][0]['port'],
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

        cmd = """export LD_LIBRARY_PATH=/usr/lib/alba; """
        cmd += """/usr/bin/alba list-osds --config {0} --to-json 2>/dev/null """.format(config_file)
        output = check_output(cmd, shell=True).strip()

        return json.loads(output)

    @staticmethod
    @celery.task(name='alba.add_cluster')
    def add_cluster(alba_backend_guid, ip, base_dir=None, client_start_port=None, messaging_start_port=None):
        """
        Adds an arakoon cluster to service backend
        """
        def _register_service(service_ip, service_name, service_type, specific_service, ports):
            service = Service()
            service.name = service_name
            service.type = service_type
            service.ports = ports
            service.storagerouter = StorageRouterList.get_by_ip(service_ip)
            service.save()
            specific_service = specific_service
            specific_service.service = service
            if service_type == nsmservice_type:
                specific_service.number = 0
            specific_service.alba_backend = albabackend
            specific_service.save()

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

        master_ips = list()
        masters = StorageRouterList.get_masters()
        for master in masters:
            master_ips.append(str(master.ip))
        master_ips.sort()

        if ip not in master_ips:
            raise RuntimeError('Arakoon cluster should be added on a master node, got {0}, expected one out of {1}'.format(ip, master_ips))

        slave_ips = list()
        slaves = StorageRouterList.get_slaves()
        for slave in slaves:
            slave_ips.append(str(slave.ip))
        slave_ips.sort()

        # deploy on first master node
        ports_to_exclude = ServiceList.get_service_ports_in_use()
        abm_result = ArakoonInstaller.create_cluster(abm_name, ip, base_dir, client_start_port, messaging_start_port,
                                                     ports_to_exclude, ArakoonInstaller.ABM_PLUGIN)
        _register_service(ip, abm_name, abmservice_type, ABMService(), [abm_result['client_port'],
                                                                        abm_result['messaging_port']])
        ports_to_exclude = ServiceList.get_service_ports_in_use()
        nsm_result = ArakoonInstaller.create_cluster(nsm_name, ip, base_dir, client_start_port, messaging_start_port,
                                                     ports_to_exclude, ArakoonInstaller.NSM_PLUGIN)
        _register_service(ip, nsm_name, nsmservice_type, NSMService(), [nsm_result['client_port'],
                                                                        nsm_result['messaging_port']])

        # extend to other master nodes
        master_ips.pop(master_ips.index(ip))
        for other_master in master_ips:
            ArakoonInstaller.extend_cluster(ip, other_master, abm_name, abm_result['client_port'], abm_result['messaging_port'])
            _register_service(other_master, abm_name, abmservice_type, ABMService(),
                              [abm_result['client_port'], abm_result['messaging_port']])
            ArakoonInstaller.extend_cluster(ip, other_master, nsm_name, nsm_result['client_port'], nsm_result['messaging_port'])
            _register_service(other_master, nsm_name, nsmservice_type, NSMService(),
                              [nsm_result['client_port'], nsm_result['messaging_port']])

        # deploy client_config to slaves
        for slave in slave_ips:
            ArakoonInstaller.deploy_client_config(ip, slave, abm_name)
            ArakoonInstaller.deploy_client_config(ip, slave, nsm_name)

        # startup arakoon clusters
        master_ips.append(ip)
        master_ips.sort()
        for master_ip in master_ips:
            ArakoonInstaller.start(abm_name, master_ip)
            ArakoonInstaller.start(nsm_name, master_ip)

        ArakoonInstaller.register_nsm(abm_name, nsm_name, ip)

        # Configure maintenance service
        for master_ip in master_ips:
            client = SSHClient.load(master_ip)
            params = {'<ALBA_CONFIG>': '{0}/{1}/{1}.cfg'.format(ArakoonInstaller.ARAKOON_CONFIG_DIR, abm_name)}
            config_file_base = '/opt/OpenvStorage/config/templates/upstart/ovs-alba-maintenance'
            if client.file_exists('{0}.conf'.format(config_file_base)):
                client.run('cp -f {0}.conf {0}_{1}.conf'.format(config_file_base, abm_name))
            service_script = """
from ovs.plugin.provider.service import Service
Service.add_service(package=('openvstorage', 'volumedriver'), name='alba-maintenance_{0}', command=None, stop_command=None, params={1})
Service.start_service('alba-maintenance_{0}')
""".format(abm_name, params)
            System.exec_remote_python(client, service_script)

        # Mark the backend as "running"
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
        config = ArakoonInstaller.get_client_config_from(backend.abm_services[0].service.storagerouter.ip,
                                                         backend.abm_services[0].service.name)
        config_dict = {}
        for section in config.sections():
            config_dict[section] = dict(config.items(section))
        return config_dict

    @staticmethod
    @setup_hook('promote')
    def on_promote(cluster_ip, master_ip):
        """
        A node is being promoted
        """
        alba_backends = AlbaBackendList.get_albabackends()
        storagerouter = StorageRouterList.get_by_ip(cluster_ip)
        abmservice_type = ServiceTypeList.get_by_name('AlbaManager')
        for alba_backend in alba_backends:
            # Make sure the ABM is extended to the new node
            print 'Extending ABM for {0}'.format(alba_backend.backend.name)
            storagerouter_ips = [abm_service.service.storagerouter.ip for abm_service in alba_backend.abm_services]
            if cluster_ip in storagerouter_ips:
                raise RuntimeError('Error executing promote in Alba plugin: IP conflict')
            abm_service = alba_backend.abm_services[0]
            service = abm_service.service
            ports_to_exclude = ServiceList.get_service_ports_in_use()
            print '* Extend ABM cluster'
            ArakoonInstaller.extend_cluster(master_ip, cluster_ip, service.name,
                                            service.ports[0], service.ports[1],
                                            ports_to_exclude)
            print '* Model new ABM node'
            AlbaController._model_service(service.name, abmservice_type, service.ports,
                                          storagerouter, ABMService, alba_backend)
            print '* Restarting ABM'
            ArakoonInstaller.restart_cluster_add(service.name, storagerouter_ips, cluster_ip)

            # Add and start an ALBA maintenance service
            print 'Adding ALBA maintenance service for {0}'.format(alba_backend.backend.name)
            client = SSHClient.load(cluster_ip)
            params = {'<ALBA_CONFIG>': '{0}/{1}/{1}.cfg'.format(ArakoonInstaller.ARAKOON_CONFIG_DIR, service.name)}
            config_file_base = '/opt/OpenvStorage/config/templates/upstart/ovs-alba-maintenance'
            if client.file_exists('{0}.conf'.format(config_file_base)):
                client.run('cp -f {0}.conf {0}_{1}.conf'.format(config_file_base, service.name))
            service_script = """
from ovs.plugin.provider.service import Service
Service.add_service(package=('openvstorage', 'volumedriver'), name='alba-maintenance_{0}', command=None, stop_command=None, params={1})
Service.start_service('alba-maintenance_{0}')
""".format(service.name, params)
            System.exec_remote_python(client, service_script)
        print 'Completed'

    @staticmethod
    @setup_hook('demote')
    def on_demote(cluster_ip, master_ip):
        """
        A node is being demoted
        """
        alba_backends = AlbaBackendList.get_albabackends()
        for alba_backend in alba_backends:
            # Remove the node from the ABM
            print 'Shrinking ABM for {0}'.format(alba_backend.backend.name)
            storagerouter_ips = [abm_service.service.storagerouter.ip for abm_service in alba_backend.abm_services]
            if cluster_ip not in storagerouter_ips:
                raise RuntimeError('Error executing promote in Alba plugin: IP conflict')
            storagerouter_ips.remove(cluster_ip)
            abm_service = [abms for abms in alba_backend.abm_services if abms.service.storagerouter.ip == cluster_ip]
            service = abm_service.service
            print '* Shrink ABM cluster'
            ArakoonInstaller.shrink_cluster(master_ip, cluster_ip, service.name, service.ports[0], service.ports[1])
            print '* Restarting ABM'
            ArakoonInstaller.restart_cluster_remove(service.name, storagerouter_ips)
            print '* Remove old ABM node from model'
            abm_service.delete()
            service.delete()

            # Stop and delete the ALBA maintenance service on this node
            print 'Removing ALBA maintenance service for {0}'.format(alba_backend.backend.name)
            client = SSHClient.load(cluster_ip)
            service_script = """
from ovs.plugin.provider.service import Service
Service.remove_service('', '{0}')
""".format(service.name)
            System.exec_remote_python(client, service_script)

    @staticmethod
    def _model_service(service_name, service_type, ports, storagerouter, junction_type, backend, number=None):
        """
        Adds service to the model
        """
        service = Service()
        service.name = service_name
        service.type = service_type
        service.ports = ports
        service.storagerouter = storagerouter
        service.save()
        junction_service = junction_type()
        junction_service.service = service
        if hasattr(junction_service, 'number'):
            if number is None:
                raise RuntimeError('A number needs to be specified')
            junction_service.number = number
        junction_service.alba_backend = backend
        junction_service.save()
