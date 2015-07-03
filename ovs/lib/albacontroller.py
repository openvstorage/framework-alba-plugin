# Copyright 2014 CloudFounders NV
# All rights reserved

"""
AlbaController module
"""

import time
import json
from tempfile import NamedTemporaryFile
from ovs.celery_run import celery
from celery.schedules import crontab
from ovs.extensions.db.arakoon.ArakoonInstaller import ArakoonInstaller, ArakoonClusterConfig
from ovs.extensions.plugins.albacli import AlbaCLI
from ovs.extensions.generic.sshclient import SSHClient
from ovs.lib.helpers.decorators import ensure_single, add_hooks
from ovs.log.logHandler import LogHandler
from ovs.dal.hybrids.j_nsmservice import NSMService
from ovs.dal.hybrids.j_abmservice import ABMService
from ovs.dal.hybrids.service import Service as DalService
from ovs.dal.hybrids.storagerouter import StorageRouter
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.albaasd import AlbaASD
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.lists.licenselist import LicenseList
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.dal.lists.servicetypelist import ServiceTypeList
from ovs.dal.lists.servicelist import ServiceList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs.extensions.generic.configuration import Configuration
from ovs.extensions.packages.package import PackageManager
from ovs.extensions.services.service import ServiceManager


logger = LogHandler.get('lib', name='alba')


class AlbaController(object):
    """
    Contains all BLL related to ALBA
    """
    ABM_PLUGIN = 'albamgr_plugin'
    NSM_PLUGIN = 'nsm_host_plugin'
    ARAKOON_PLUGIN_DIR = '/usr/lib/alba'
    ALBA_MAINTENANCE_SERVICE_PREFIX = 'alba-maintenance'
    ALBA_REBALANCER_SERVICE_PREFIX = 'alba-rebalancer'

    @staticmethod
    @celery.task(name='alba.add_units')
    def add_units(alba_backend_guid, asds):
        """
        Adds storage units to an Alba backend
        """
        alba_backend = AlbaBackend(alba_backend_guid)
        config_file = '/opt/OpenvStorage/config/arakoon/{0}/{0}.cfg'.format(alba_backend.backend.name + '-abm')
        for asd_id, node_guid in asds.iteritems():
            AlbaCLI.run('claim-osd', config=config_file, long_id=asd_id, as_json=True)
            asd = AlbaASD()
            asd.asd_id = asd_id
            asd.alba_node = AlbaNode(node_guid)
            asd.alba_backend = alba_backend
            asd.save()
            asd.alba_node.invalidate_dynamics()
        alba_backend.invalidate_dynamics()
        alba_backend.backend.invalidate_dynamics()

    @staticmethod
    @celery.task(name='alba.remove_units')
    def remove_units(alba_backend_guid, asd_ids, absorb_exception=False):
        """
        Removes storage units to an Alba backend
        """
        try:
            alba_backend = AlbaBackend(alba_backend_guid)
            config_file = '/opt/OpenvStorage/config/arakoon/{0}/{0}.cfg'.format(alba_backend.backend.name + '-abm')
            for asd_id in asd_ids:
                AlbaCLI.run('decommission-osd', config=config_file, long_id=asd_id)
        except:
            if absorb_exception is False:
                raise

    @staticmethod
    @celery.task(name='alba.add_preset')
    def add_preset(alba_backend_guid, name, compression, policies):
        """
        Adds a preset to Alba
        """
        alba_backend = AlbaBackend(alba_backend_guid)
        if name in [preset['name'] for preset in alba_backend.presets]:
            raise RuntimeError('Preset name {0} already exists'.format(name))
        logger.debug('Adding preset {0} with compression {1} and policies {2}'.format(name, compression, policies))
        preset = {'compression': compression,
                  'object_checksum': {'default': ['crc-32c'], 'verify_upload': True, 'allowed': [['none'], ['sha-1'], ['crc-32c']]},
                  'osds': ['all'],
                  'fragment_encryption': ['none'],
                  'fragment_size': 1048576,
                  'policies': policies,
                  'fragment_checksum': ['crc-32c'],
                  'in_use': False,
                  'name': name}
        config_file = '/opt/OpenvStorage/config/arakoon/{0}/{0}.cfg'.format(alba_backend.backend.name + '-abm')
        with NamedTemporaryFile() as data_file:
            data_file.write(json.dumps(preset))
            data_file.flush()
            AlbaCLI.run('create-preset', config=config_file, extra_params=[name, '<', data_file.name], as_json=True)
            alba_backend.invalidate_dynamics()

    @staticmethod
    @celery.task(name='alba.delete_preset')
    def delete_preset(alba_backend_guid, name):
        """
        Deletes a preset from the Alba backend
        """
        alba_backend = AlbaBackend(alba_backend_guid)
        logger.debug('Deleting preset {0}'.format(name))
        config_file = '/opt/OpenvStorage/config/arakoon/{0}/{0}.cfg'.format(alba_backend.backend.name + '-abm')
        AlbaCLI.run('delete-preset', config=config_file, extra_params=name, as_json=True)
        alba_backend.invalidate_dynamics()

    @staticmethod
    @celery.task(name='alba.add_cluster')
    def add_cluster(alba_backend_guid, storagerouter_guid):
        """
        Adds an arakoon cluster to service backend
        """
        nsmservice_type = ServiceTypeList.get_by_name('NamespaceManager')
        abmservice_type = ServiceTypeList.get_by_name('AlbaManager')

        albabackend = AlbaBackend(alba_backend_guid)
        abm_name = albabackend.backend.name + "-abm"
        nsm_name = albabackend.backend.name + "-nsm_0"

        storagerouter = StorageRouter(storagerouter_guid)
        masters = StorageRouterList.get_masters()
        if storagerouter not in masters:
            raise RuntimeError('Arakoon cluster should be added on a master node')
        slaves = StorageRouterList.get_slaves()

        used_ports = {}
        for sr in masters + slaves:
            if sr not in used_ports:
                used_ports[sr] = []
        for service in ServiceList.get_services():
            if service.storagerouter not in used_ports:
                used_ports[service.storagerouter] = []
            used_ports[service.storagerouter] += service.ports

        # deploy on first master node
        ports_to_exclude = used_ports[storagerouter]
        abm_result = ArakoonInstaller.create_cluster(abm_name, storagerouter.ip, ports_to_exclude, AlbaController.ABM_PLUGIN)
        AlbaController.link_plugins(SSHClient(storagerouter.ip), [AlbaController.ABM_PLUGIN], abm_name)
        ports = [abm_result['client_port'], abm_result['messaging_port']]
        AlbaController._model_service(abm_name, abmservice_type, ports, storagerouter, ABMService, albabackend)
        ports_to_exclude += ports
        nsm_result = ArakoonInstaller.create_cluster(nsm_name, storagerouter.ip, ports_to_exclude, AlbaController.NSM_PLUGIN)
        AlbaController.link_plugins(SSHClient(storagerouter.ip), [AlbaController.NSM_PLUGIN], nsm_name)
        ports = [nsm_result['client_port'], nsm_result['messaging_port']]
        AlbaController._model_service(nsm_name, nsmservice_type, ports, storagerouter, NSMService, albabackend, 0)

        # extend to other master nodes
        for master in masters:
            if master == storagerouter:
                continue
            ports_to_exclude = used_ports[master]
            abm_result = ArakoonInstaller.extend_cluster(storagerouter.ip, master.ip, abm_name, ports_to_exclude)
            AlbaController.link_plugins(SSHClient(master.ip), [AlbaController.ABM_PLUGIN], abm_name)
            ports = [abm_result['client_port'], abm_result['messaging_port']]
            AlbaController._model_service(abm_name, abmservice_type, ports, master, ABMService, albabackend)
            ports_to_exclude += ports
            nsm_result = ArakoonInstaller.extend_cluster(storagerouter.ip, master.ip, nsm_name, ports_to_exclude)
            AlbaController.link_plugins(SSHClient(master.ip), [AlbaController.NSM_PLUGIN], nsm_name)
            ports = [nsm_result['client_port'], nsm_result['messaging_port']]
            AlbaController._model_service(nsm_name, nsmservice_type, ports, master, NSMService, albabackend, 0)

        # deploy client_config to slaves
        for slave in slaves:
            ArakoonInstaller.deploy_to_slave(storagerouter.ip, slave.ip, abm_name)
            ArakoonInstaller.deploy_to_slave(storagerouter.ip, slave.ip, nsm_name)

        # startup arakoon clusters
        for master in masters:
            client = SSHClient(master.ip, username='root')
            ArakoonInstaller.start(abm_name, client)
            ArakoonInstaller.start(nsm_name, client)

        AlbaController.register_nsm(abm_name, nsm_name, storagerouter.ip)

        # Configure maintenance service
        for master in masters:
            AlbaController._setup_service('maintenance', master.ip, abm_name, albabackend.backend.name)
            AlbaController._setup_service('rebalancer', master.ip, abm_name, albabackend.backend.name)

        config_file = '/opt/OpenvStorage/config/arakoon/{0}/{0}.cfg'.format(albabackend.backend.name + '-abm')
        albabackend.alba_id = AlbaCLI.run('get-alba-id', config=config_file, as_json=True)['id']
        albabackend.save()

        lic = LicenseList.get_by_component('alba')
        if lic is not None:
            AlbaController.apply(lic.component, lic.data, lic.signature, alba_backend=albabackend)

        # Mark the backend as "running"
        albabackend.backend.status = 'RUNNING'
        albabackend.backend.save()

    @staticmethod
    @celery.task(name='alba.remove_cluster')
    def remove_cluster(alba_backend_guid):
        """
        Removes an Alba backend/cluster
        """
        albabackend = AlbaBackend(alba_backend_guid)
        if len(albabackend.asds) > 0:
            raise RuntimeError('A backend with claimed OSDs cannot be removed')

        slaves = StorageRouterList.get_slaves()
        masters = StorageRouterList.get_masters()

        abm_name = albabackend.backend.name + '-abm'
        for master in masters:
            AlbaController._remove_service('maintenance', master.ip, abm_name, albabackend.backend.name)
            AlbaController._remove_service('rebalancer', master.ip, abm_name, albabackend.backend.name)

        cluster_removed = False
        for abm_service in albabackend.abm_services:
            ip = abm_service.service.storagerouter.ip
            service_name = abm_service.service.name
            if cluster_removed is False:
                for slave in slaves:
                    ArakoonInstaller.remove_from_slave(ip, slave.ip, service_name)
                ArakoonInstaller.delete_cluster(service_name, ip)
                cluster_removed = True
            service = abm_service.service
            abm_service.delete()
            service.delete()

        cluster_removed = []
        for nsm_service in albabackend.nsm_services:
            if nsm_service.service.name not in cluster_removed:
                ArakoonInstaller.delete_cluster(nsm_service.service.name, nsm_service.service.storagerouter.ip)
                cluster_removed.append(nsm_service.service.name)
            service = nsm_service.service
            nsm_service.delete()
            service.delete()

        backend = albabackend.backend
        albabackend.delete()
        backend.delete()

    @staticmethod
    @celery.task(name='alba.get_config_metadata')
    def get_config_metadata(alba_backend_guid):
        """
        Gets the configuration metadata for an Alba backend
        """
        service = AlbaBackend(alba_backend_guid).abm_services[0].service
        config = ArakoonClusterConfig(service.name)
        config.load_config(SSHClient(service.storagerouter.ip))
        return config.export()

    @staticmethod
    def link_plugins(client, plugins, cluster_name):
        data_dir = client.config_read('ovs.arakoon.location')
        for plugin in plugins:
            cmd = 'ln -s {0}/{3}.cmxs {1}/arakoon/{2}/'.format(AlbaController.ARAKOON_PLUGIN_DIR, data_dir, cluster_name, plugin)
            client.run(cmd)

    @staticmethod
    @add_hooks('setup', 'promote')
    def on_promote(cluster_ip, master_ip):
        """
        A node is being promoted
        """
        abmservice_type = ServiceTypeList.get_by_name('AlbaManager')
        alba_backends = AlbaBackendList.get_albabackends()
        storagerouter = StorageRouterList.get_by_ip(cluster_ip)
        ports_to_exclude = ServiceList.get_ports_for_ip(cluster_ip)
        for alba_backend in alba_backends:
            # Make sure the ABM is extended to the new node
            print 'Extending ABM for {0}'.format(alba_backend.backend.name)
            storagerouter_ips = [abm_service.service.storagerouter.ip for abm_service in alba_backend.abm_services]
            if cluster_ip in storagerouter_ips:
                raise RuntimeError('Error executing promote in Alba plugin: IP conflict')
            abm_service = alba_backend.abm_services[0]
            service = abm_service.service
            print '* Extend ABM cluster'
            abm_result = ArakoonInstaller.extend_cluster(master_ip, cluster_ip, service.name, ports_to_exclude)
            AlbaController.link_plugins(SSHClient(cluster_ip), [AlbaController.ABM_PLUGIN], service.name)
            ports = [abm_result['client_port'], abm_result['messaging_port']]
            ports_to_exclude += ports
            print '* Model new ABM node'
            AlbaController._model_service(service.name, abmservice_type, ports,
                                          storagerouter, ABMService, alba_backend)
            print '* Restarting ABM'
            ArakoonInstaller.restart_cluster_add(service.name, storagerouter_ips, cluster_ip)

            # Add and start an ALBA maintenance service
            print 'Adding ALBA services for {0}'.format(alba_backend.backend.name)
            AlbaController._setup_service('maintenance', cluster_ip, service.name, alba_backend.backend.name)
            AlbaController._setup_service('rebalancer', cluster_ip, service.name, alba_backend.backend.name)

    @staticmethod
    @add_hooks('setup', 'demote')
    def on_demote(cluster_ip, master_ip):
        """
        A node is being demoted
        """
        alba_backends = AlbaBackendList.get_albabackends()
        client = SSHClient(cluster_ip, username='root')
        for alba_backend in alba_backends:
            # Remove the node from the ABM
            print 'Shrinking ABM for {0}'.format(alba_backend.backend.name)
            storagerouter_ips = [abm_service.service.storagerouter.ip for abm_service in alba_backend.abm_services]
            if cluster_ip not in storagerouter_ips:
                raise RuntimeError('Error executing promote in Alba plugin: IP conflict')
            storagerouter_ips.remove(cluster_ip)
            abm_service = [abms for abms in alba_backend.abm_services if abms.service.storagerouter.ip == cluster_ip][0]
            service = abm_service.service
            print '* Shrink ABM cluster'
            ArakoonInstaller.shrink_cluster(master_ip, cluster_ip, service.name)
            if ServiceManager.has_service('arakoon-{0}'.format(service.name), client=client) is True:
                ServiceManager.stop_service('arakoon-{0}'.format(service.name), client=client)
                ServiceManager.remove_service('arakoon-{0}'.format(service.name), client=client)

            print '* Restarting ABM'
            ArakoonInstaller.restart_cluster_remove(service.name, storagerouter_ips)
            print '* Remove old ABM node from model'
            abm_service.delete()
            service.delete()

            # Stop and delete the ALBA maintenance service on this node
            AlbaController._remove_service('maintenance', client.ip, service.name, alba_backend.backend.name)
            AlbaController._remove_service('rebalancer', client.ip, service.name, alba_backend.backend.name)

    @staticmethod
    @celery.task(name='alba.nsm_checkup', bind=True, schedule=crontab(minute='30', hour='0'))
    @ensure_single(['alba.nsm_checkup'])
    def nsm_checkup():
        """
        Validates the current NSM setup/configuration and takes actions where required.
        Assumptions:
        * A 2 node NSM is considered safer than a 1 node NSM.
        * When adding an NSM, the nodes with the least amount of NSM participation are preferred
        """
        nsmservice_type = ServiceTypeList.get_by_name('NamespaceManager')
        safety = Configuration.get('alba.nsm.safety')
        maxload = Configuration.get('alba.nsm.maxload')
        used_ports = {}
        for service in ServiceList.get_services():
            if service.storagerouter not in used_ports:
                used_ports[service.storagerouter] = []
            used_ports[service.storagerouter] += service.ports
        for backend in AlbaBackendList.get_albabackends():
            abm_service = backend.abm_services[0]
            service_name = abm_service.service.name
            logger.debug('Ensuring NSM safety for backend {0}'.format(service_name))
            nsm_groups = {}
            nsm_storagerouter = {}
            for abms in backend.abm_services:
                storagerouter = abms.service.storagerouter
                if storagerouter not in nsm_storagerouter:
                    nsm_storagerouter[storagerouter] = 0
            for nsm_service in backend.nsm_services:
                number = nsm_service.number
                if number not in nsm_groups:
                    nsm_groups[number] = []
                nsm_groups[number].append(nsm_service)
                storagerouter = nsm_service.service.storagerouter
                if storagerouter not in nsm_storagerouter:
                    nsm_storagerouter[storagerouter] = 0
                nsm_storagerouter[storagerouter] += 1
            maxnumber = max(nsm_groups.keys())
            for number in nsm_groups:
                logger.debug('Processing NSM {0}'.format(number))
                # Check amount of nodes
                if len(nsm_groups[number]) < safety:
                    logger.debug('Insufficient nodes, extending if possible')
                    # Not enough nodes, let's see what can be done
                    current_srs = [nsm_service.service.storagerouter for nsm_service in nsm_groups[number]]
                    current_nsm = nsm_groups[number][0]
                    available_srs = [storagerouter for storagerouter in nsm_storagerouter.keys()
                                     if storagerouter not in current_srs]
                    service_name = current_nsm.service.name
                    # As long as there are available StorageRouters and there are still not enough StorageRouters configured
                    while len(available_srs) > 0 and len(current_srs) < safety:
                        logger.debug('Adding node')
                        candidate_sr = None
                        candidate_load = None
                        for storagerouter in available_srs:
                            if candidate_load is None:
                                candidate_sr = storagerouter
                                candidate_load = nsm_storagerouter[storagerouter]
                            elif nsm_storagerouter[storagerouter] < candidate_load:
                                candidate_sr = storagerouter
                                candidate_load = nsm_storagerouter[storagerouter]
                        current_srs.append(candidate_sr)
                        available_srs.remove(candidate_sr)
                        # Extend the cluster (configuration, services, ...)
                        if candidate_sr not in used_ports:
                            used_ports[candidate_sr] = []
                        logger.debug('  Extending cluster config')
                        nsm_result = ArakoonInstaller.extend_cluster(current_nsm.service.storagerouter.ip, candidate_sr.ip,
                                                                     service_name, used_ports[candidate_sr])
                        logger.debug('  Linking plugin')
                        AlbaController.link_plugins(SSHClient(candidate_sr.ip), [AlbaController.NSM_PLUGIN], service_name)
                        ports = [nsm_result['client_port'], nsm_result['messaging_port']]
                        used_ports[candidate_sr] += ports
                        logger.debug('  Model services')
                        AlbaController._model_service(service_name, nsmservice_type, ports,
                                                      candidate_sr, NSMService, backend, current_nsm.number)
                        logger.debug('  Restart sequence')
                        ArakoonInstaller.restart_cluster_add(service_name, [sr.ip for sr in current_srs], candidate_sr.ip)
                        AlbaController.update_nsm(abm_service.service.name, service_name, candidate_sr.ip)
                        logger.debug('Node added')

                # Check the cluster load
                overloaded = False
                for service in nsm_groups[number]:
                    load = AlbaController.get_load(service)
                    if load > maxload:
                        overloaded = True
                        break
                if overloaded is True:
                    logger.debug('NSM overloaded, adding new NSM')
                    # On of the this NSM's node is overloaded. This means the complete NSM is considered overloaded
                    # Figure out which StorageRouters are the least occupied
                    storagerouters = []
                    for storagerouter in nsm_storagerouter:
                        count = nsm_storagerouter[storagerouter]
                        if len(storagerouters) < safety:
                            storagerouters.append((storagerouter, count))
                        else:
                            maxcount = max(sr[1] for sr in storagerouters)
                            if count < maxcount:
                                new_storagerouters = []
                                for sr in storagerouters:
                                    if sr[1] == maxload:
                                        new_storagerouters.append((storagerouter, count))
                                    else:
                                        new_storagerouters.append(sr)
                                storagerouters = new_storagerouters[:]
                    # Cloning one of the NSMs to the found StorageRouters
                    storagerouters = [storagerouter[0] for storagerouter in storagerouters]
                    maxnumber += 1
                    nsm_name = '{0}-nsm_{1}'.format(backend.backend.name, maxnumber)
                    first_ip = None
                    for storagerouter in storagerouters:
                        if storagerouter not in used_ports:
                            used_ports[storagerouter] = []
                        if first_ip is None:
                            nsm_result = ArakoonInstaller.create_cluster(nsm_name, storagerouter.ip, used_ports[storagerouter], AlbaController.NSM_PLUGIN)
                            AlbaController.link_plugins(SSHClient(storagerouter.ip), [AlbaController.NSM_PLUGIN], nsm_name)
                            ports = [nsm_result['client_port'], nsm_result['messaging_port']]
                            used_ports[storagerouter] += ports
                            AlbaController._model_service(nsm_name, nsmservice_type, ports,
                                                          storagerouter, NSMService, backend, maxnumber)
                            first_ip = storagerouter.ip
                        else:
                            nsm_result = ArakoonInstaller.extend_cluster(first_ip, storagerouter.ip, nsm_name, used_ports[storagerouter])
                            AlbaController.link_plugins(SSHClient(storagerouter.ip), [AlbaController.NSM_PLUGIN], nsm_name)
                            ports = [nsm_result['client_port'], nsm_result['messaging_port']]
                            used_ports[storagerouter] += ports
                            AlbaController._model_service(nsm_name, nsmservice_type, ports,
                                                          storagerouter, NSMService, backend, maxnumber)
                    for storagerouter in storagerouters:
                        client = SSHClient(storagerouter.ip, username='root')
                        ArakoonInstaller.start(nsm_name, client)
                    AlbaController.register_nsm(abm_service.service.name, nsm_name, storagerouters[0].ip)
                    logger.debug('New NSM ({0}) added'.format(maxnumber))
                else:
                    logger.debug('NSM load OK')

    @staticmethod
    @celery.task(name='alba.calculate_safety')
    def calculate_safety(alba_backend_guid, removal_asd_ids):
        """
        Calculates/loads the safety when a certain set of disks are removed
        """
        alba_backend = AlbaBackend(alba_backend_guid)
        error_disks = [disk['asd_id'] for disk in alba_backend.all_disks if 'asd_id' in disk and 'status' in disk and disk['status'] == 'error']
        extra_parameters = ['--include-decommissioning-as-dead']
        for asd in alba_backend.asds:
            if asd.asd_id in removal_asd_ids or asd.asd_id in error_disks:
                extra_parameters.append('--long-id {0}'.format(asd.asd_id))
        config_file = '/opt/OpenvStorage/config/arakoon/{0}/{0}.cfg'.format(alba_backend.backend.name + '-abm')
        safety_data = AlbaCLI.run('get-disk-safety', config=config_file, extra_params=extra_parameters, as_json=True)
        result = {'good': 0,
                  'critical': 0,
                  'lost': 0}
        for namespace in safety_data:
            safety = namespace['safety']
            if safety is None or safety > 0:
                result['good'] += 1
            elif safety == 0:
                result['critical'] += 1
            else:
                result['lost'] += 1
        return result

    @staticmethod
    def get_load(nsm_service):
        """
        Calculates the load of an NSM node, returning a float percentage
        """
        service_capacity = float(nsm_service.capacity)
        if service_capacity < 0:
            return 50
        if service_capacity == 0:
            return float('inf')
        filename = ArakoonInstaller.ARAKOON_CONFIG_FILE.format(nsm_service.alba_backend.abm_services[0].service.name)
        hosts_data = AlbaCLI.run('list-nsm-hosts', config=filename, as_json=True)
        host = [host for host in hosts_data if host['id'] == nsm_service.service.name][0]
        usage = host['namespaces_count']
        return round(usage / service_capacity * 100.0, 5)

    @staticmethod
    def register_nsm(abm_name, nsm_name, ip):
        nsm_config_file = ArakoonInstaller.ARAKOON_CONFIG_FILE.format(nsm_name)
        abm_config_file = ArakoonInstaller.ARAKOON_CONFIG_FILE.format(abm_name)
        if ArakoonInstaller.wait_for_cluster(nsm_name) and ArakoonInstaller.wait_for_cluster(abm_name):
            client = SSHClient(ip)
            AlbaCLI.run('add-nsm-host', config=abm_config_file, extra_params=nsm_config_file, client=client)

    @staticmethod
    def update_nsm(abm_name, nsm_name, ip):
        nsm_config_file = ArakoonInstaller.ARAKOON_CONFIG_FILE.format(nsm_name)
        abm_config_file = ArakoonInstaller.ARAKOON_CONFIG_FILE.format(abm_name)
        if ArakoonInstaller.wait_for_cluster(nsm_name) and ArakoonInstaller.wait_for_cluster(abm_name):
            client = SSHClient(ip)
            AlbaCLI.run('update-nsm-host', config=abm_config_file, extra_params=nsm_config_file, client=client)

    @staticmethod
    def _model_service(service_name, service_type, ports, storagerouter, junction_type, backend, number=None):
        """
        Adds service to the model
        """
        service = DalService()
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
        return junction_service

    @staticmethod
    @add_hooks('license', 'alba.validate')
    def validate(component, data, signature):
        """
        Validates an Alba license
        """
        if component != 'alba':
            raise RuntimeError('Invalid component {0} in license.alba.validate'.format(component))
        with NamedTemporaryFile() as data_file:
            data_file.write(json.dumps(data, sort_keys=True))
            data_file.flush()
            success, _ = AlbaCLI.run('verify-license', extra_params=[data_file.name, signature], as_json=True, raise_on_failure=False)
            return success, data

    @staticmethod
    @add_hooks('license', 'alba.sign')
    def sign(component, data):
        """
        Signs data, returns the signature
        """
        if component != 'alba':
            raise RuntimeError('Invalid component {0} in license.alba.sign'.format(component))
        with NamedTemporaryFile() as data_file:
            data_file.write(json.dumps(data, sort_keys=True))
            data_file.flush()
            return AlbaCLI.run('sign-license', extra_params=['/opt/OpenvStorage/config/alba_private.key', data_file.name], as_json=True)

    @staticmethod
    @add_hooks('license', 'alba.apply')
    def apply(component, data, signature, alba_backend=None):
        """
        Applies a license to Alba
        """
        if component != 'alba':
            raise RuntimeError('Invalid component {0} in license.alba.apply'.format(component))
        alba_backends = [alba_backend] if alba_backend is not None else AlbaBackendList.get_albabackends()
        with NamedTemporaryFile() as data_file:
            data_file.write(json.dumps(data, sort_keys=True))
            data_file.flush()
            success = True
            for alba_backend in alba_backends:
                config_file = '/opt/OpenvStorage/config/arakoon/{0}/{0}.cfg'.format(alba_backend.backend.name + '-abm')
                run_success, _ = AlbaCLI.run('apply-license', config=config_file, extra_params=[data_file.name, signature], as_json=True, raise_on_failure=False)
                success &= run_success
            return success

    @staticmethod
    @add_hooks('update', 'metadata')
    def get_metadata_alba(client):
        """
        Retrieve ALBA packages and services which ALBA depends upon
        Also check the arakoon clusters to be able to warn the customer for potential downtime
        :client: SSHClient on which to retrieve the metadata
        :return: List of dictionaries which contain services to restart,
                                                    packages to update,
                                                    information about potential downtime
                                                    information about unmet prerequisites
        """
        logger.info('Retrieving metadata for ALBA plugin update')
        downtime = []
        alba_services = set()
        arakoon_cluster_services = set()
        for albabackend in AlbaBackendList.get_albabackends():
            alba_services.add('{0}_{1}'.format(AlbaController.ALBA_MAINTENANCE_SERVICE_PREFIX, albabackend.backend.name))
            alba_services.add('{0}_{1}'.format(AlbaController.ALBA_REBALANCER_SERVICE_PREFIX, albabackend.backend.name))
            arakoon_cluster_services.add('arakoon-{0}'.format(albabackend.abm_services[0].service.name))
            arakoon_cluster_services.update(['arakoon-{0}'.format(service.service.name) for service in albabackend.nsm_services])
            if len(albabackend.abm_services) < 3:
                downtime.append(('alba', 'backend', albabackend.backend.name))
                continue  # No need to check other services for this backend since downtime is a fact

            nsm_service_info = {}
            for service in albabackend.nsm_services:
                if service.service.name not in nsm_service_info:
                    nsm_service_info[service.service.name] = 0
                nsm_service_info[service.service.name] += 1
            if min(nsm_service_info.values()) < 3:
                downtime.append(('alba', 'backend', albabackend.backend.name))

        core_info = PackageManager.verify_update_required(packages=['openvstorage-backend-core', 'openvstorage-backend-webapps'],
                                                          services=[],
                                                          client=client)
        alba_info = PackageManager.verify_update_required(packages=['alba'],
                                                          services=list(alba_services),
                                                          client=client)
        arakoon_info = PackageManager.verify_update_required(packages=['arakoon'],
                                                             services=arakoon_cluster_services,
                                                             client=client)

        return {'framework': [{'name': 'openvstorage-backend',
                               'version': core_info['version'],
                               'services': core_info['services'],
                               'packages': core_info['packages'],
                               'downtime': [],
                               'namespace': 'alba',
                               'prerequisites': []},
                              {'name': 'alba',
                               'version': alba_info['version'],
                               'services': alba_info['services'],
                               'packages': alba_info['packages'],
                               'downtime': downtime,
                               'namespace': 'alba',
                               'prerequisites': []},
                              {'name': 'arakoon',
                               'version': arakoon_info['version'],
                               'services': arakoon_info['services'],
                               'packages': arakoon_info['packages'],
                               'downtime': downtime,
                               'namespace': 'alba',
                               'prerequisites': []}]}

    @staticmethod
    @add_hooks('update', 'postupgrade')
    def restart_arakoon_clusters(master_ip):
        """
        Restart all arakoon clusters after arakoon and/or alba package upgrade
        :param master_ip: IP of 1 of the masternodes (On which the update is initiated)
        :return: None
        """
        for alba_backend in AlbaBackendList.get_albabackends():
            logger.info('Restarting clusters for backend {0}'.format(alba_backend.name), print_msg=True)
            storagerouter_ips = [abm_service.service.storagerouter.ip for abm_service in alba_backend.abm_services]
            if master_ip not in storagerouter_ips:
                raise RuntimeError('Error executing restart in Alba plugin: IP conflict')

            logger.info('Restarting ABM cluster', print_msg=True)
            abm_service = alba_backend.abm_services[0].service
            ArakoonInstaller.restart_cluster(cluster_name=abm_service.name,
                                             master_ip=master_ip)

            unique_nsm_services = dict((service.service.name, service) for service in alba_backend.nsm_services)
            for nsm_service in unique_nsm_services.itervalues():
                logger.info('Restarting NSM cluster {0}'.format(nsm_service.number), print_msg=True)
                ArakoonInstaller.restart_cluster(cluster_name=nsm_service.service.name,
                                                 master_ip=master_ip)

    @staticmethod
    def _setup_service(service_type, ip, abm_name, backend_name):
        """
        Creates and starts a maintenance service/process
        """
        if service_type == 'maintenance':
            service_prefix = AlbaController.ALBA_MAINTENANCE_SERVICE_PREFIX
        elif service_type == 'rebalancer':
            service_prefix = AlbaController.ALBA_REBALANCER_SERVICE_PREFIX
        else:
            raise RuntimeError('Unknown service type')
        ovs_client = SSHClient(ip)
        root_client = SSHClient(ip, username='root')
        json_filename = '{0}/{1}/{2}-{3}.json'.format(ArakoonInstaller.ARAKOON_CONFIG_DIR, abm_name, backend_name, service_type)
        ovs_client.file_write(json_filename, json.dumps({
            'log_level': 'debug',
            'albamgr_cfg_file': '{0}/{1}/{1}.cfg'.format(ArakoonInstaller.ARAKOON_CONFIG_DIR, abm_name)
        }))
        params = {'ALBA_CONFIG': json_filename}
        service_name = '{0}_{1}'.format(service_prefix, backend_name)
        ServiceManager.prepare_template('ovs-{0}'.format(service_prefix), 'ovs-{0}'.format(service_name), client=ovs_client)
        ServiceManager.add_service(name=service_name, params=params, client=root_client)
        ServiceManager.start_service(service_name, root_client)

    @staticmethod
    def _remove_service(service_type, ip, abm_name, backend_name):
        """
        Stops and removes the maintenance service/process
        """
        if service_type == 'maintenance':
            service_prefix = AlbaController.ALBA_MAINTENANCE_SERVICE_PREFIX
        elif service_type == 'rebalancer':
            service_prefix = AlbaController.ALBA_REBALANCER_SERVICE_PREFIX
        else:
            raise RuntimeError('Unknown service type')
        client = SSHClient(ip, username='root')
        json_filename = '{0}/{1}/{2}-{3}.json'.format(ArakoonInstaller.ARAKOON_CONFIG_DIR, abm_name, backend_name, service_type)
        service_name = '{0}_{1}'.format(service_prefix, backend_name)
        if ServiceManager.has_service(service_name, client=client) is True:
            if ServiceManager.get_service_status(service_name, client=client) is True:
                ServiceManager.stop_service(service_name, client=client)
            ServiceManager.remove_service(service_name, client=client)
        client.file_delete(json_filename)

if __name__ == '__main__':
    try:
        while True:
            _output = ['',
                       'Open vStorage - NSM/ABM debug information',
                       '=========================================',
                       'timestamp: {0}'.format(time.time()),
                       '']
            sr_backends = {}
            _alba_backends = AlbaBackendList.get_albabackends()
            for _sr in StorageRouterList.get_storagerouters():
                _output.append('+ {0} ({1})'.format(_sr.name, _sr.ip))
                for _alba_backend in _alba_backends:
                    _output.append('  + {0}'.format(_alba_backend.backend.name))
                    for _abm_service in _alba_backend.abm_services:
                        if _abm_service.service.storagerouter_guid == _sr.guid:
                            _output.append('    + ABM - port {0}'.format(_abm_service.service.ports))
                    for _nsm_service in _alba_backend.nsm_services:
                        if _nsm_service.service.storagerouter_guid == _sr.guid:
                            _service_capacity = float(_nsm_service.capacity)
                            if _service_capacity < 0:
                                _service_capacity = 'infinite'
                            _load = AlbaController.get_load(_nsm_service)
                            if _load == float('inf'):
                                _load = 'infinite'
                            else:
                                _load = '{0}%'.format(round(_load, 2))
                            _output.append('    + NSM {0} - port {1} - capacity: {2}, load: {3}'.format(
                                _nsm_service.number, _nsm_service.service.ports, _service_capacity, _load
                            ))
            _output += ['',
                        'Press ^C to exit',
                        '']
            print '\x1b[2J\x1b[H' + '\n'.join(_output)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
