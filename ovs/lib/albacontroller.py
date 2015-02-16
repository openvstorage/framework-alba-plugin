# Copyright 2014 CloudFounders NV
# All rights reserved

"""
AlbaController module
"""

import time
from ovs.celery_run import celery
from celery.schedules import crontab
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.lists.servicelist import ServiceList
from ovs.extensions.db.arakoon.ArakoonInstaller import ArakoonInstaller
from ovs.extensions.plugins.albacli import AlbaCLI
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
            cmd += """/usr/bin/alba claim-osd --config {0} """.format(config_file)
            cmd += """--long-id {0}""".format(device['id'])
            output = check_output(cmd, shell=True).strip()
            logger.info('** abm response:' + str(output))

    @staticmethod
    @celery.task(name='alba.list_discovered_osds')
    def list_discovered_osds(alba_backend_guid):
        """
        list discovered osds on local alba manager
        """
        alba_backend = AlbaBackend(alba_backend_guid)
        config_file = '/opt/OpenvStorage/config/arakoon/{0}/{0}.cfg'.format(alba_backend.backend.name + '-abm')

        cmd = """export LD_LIBRARY_PATH=/usr/lib/alba; """
        cmd += """/usr/bin/alba list-available-osds --config {0} --to-json 2>/dev/null """.format(config_file)
        output = check_output(cmd, shell=True).strip()

        return json.loads(output)

    @staticmethod
    @celery.task(name='alba.list_osds')
    def list_registered_osds(alba_backend_guid):
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
    @celery.task(name='alba.nsm_checkup', bind=True, schedule=crontab(minute='30', hour='0'))
    @ensure_single(['alba.nsm_checkup'])
    def nsm_checkup():
        """
        Validates the current NSM setup/configuration and takes actions where required.
        Assumptions:
        * A 2 node NSM is considered safer than a 1 node NSM.
        * When adding an NSM, the nodes with the least amount of NSM participation are preferred
        """
        base_dir = Configuration.get('ovs.arakoon.base.dir')
        client_start_port = int(Configuration.get('ovs.arakoon.client.port'))
        messaging_start_port = int(Configuration.get('ovs.arakoon.messaging.port'))
        nsmservice_type = ServiceTypeList.get_by_name('NamespaceManager')
        safety = int(Configuration.get('alba.nsm.safety'))
        maxload = int(Configuration.get('alba.nsm.maxload'))
        for backend in AlbaBackendList.get_albabackends():
            service_name = backend.abm_services[0].service.name
            logger.debug('Ensuring NSM safety for backend {0}'.format(service_name))
            nsm_groups = {}
            nsm_storagerouter = {}
            for abm_service in backend.abm_services:
                storagerouter = abm_service.service.storagerouter
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
                        ArakoonInstaller.extend_cluster(current_nsm.service.storagerouter.ip, candidate_sr.ip,
                                                        service_name,
                                                        current_nsm.service.ports[0], current_nsm.service.ports[1])
                        # Add the service to the model
                        AlbaController._model_service(service_name, nsmservice_type,
                                                      [current_nsm.service.ports[0], current_nsm.service.ports[1]],
                                                      candidate_sr, NSMService, backend, current_nsm.number)
                        ArakoonInstaller.restart_cluster_add(service_name, [sr.ip for sr in current_srs],
                                                             candidate_sr.ip)
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
                    nsm_result = {}
                    for storagerouter in storagerouters:
                        ports_to_exclude = ServiceList.get_service_ports_in_use()
                        if first_ip is None:
                            nsm_result = ArakoonInstaller.create_cluster(nsm_name, storagerouter.ip, base_dir,
                                                                         client_start_port, messaging_start_port,
                                                                         ports_to_exclude, ArakoonInstaller.NSM_PLUGIN)
                            AlbaController._model_service(nsm_name, nsmservice_type,
                                                          [nsm_result['client_port'], nsm_result['messaging_port']],
                                                          storagerouter, NSMService, backend, maxnumber)
                            first_ip = storagerouter.ip
                        else:
                            ArakoonInstaller.extend_cluster(first_ip, storagerouter.ip, nsm_name,
                                                            nsm_result['client_port'],
                                                            nsm_result['messaging_port'], ports_to_exclude)
                            AlbaController._model_service(nsm_name, nsmservice_type,
                                                          [nsm_result['client_port'], nsm_result['messaging_port']],
                                                          storagerouter, NSMService, backend, maxnumber)
                    for storagerouter in storagerouters:
                        ArakoonInstaller.start(nsm_name, storagerouter.ip)
                    logger.debug('New NSM ({0}) added'.format(maxnumber))
                else:
                    logger.debug('NSM load OK')

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
        filename = '{0}/{1}/{1}.cfg'.format(ArakoonInstaller.ARAKOON_CONFIG_DIR,
                                            nsm_service.alba_backend.abm_services[0].service.name)
        namespaces = AlbaCLI.run('list-namespaces', config=filename, as_json=True, debug=True)
        usage = len([ns for ns in namespaces if ns['nsm_host_id'] == nsm_service.service.name])
        return round(usage / service_capacity * 100.0, 5)

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


if __name__ == '__main__':
    from ovs.dal.lists.storagerouterlist import StorageRouterList
    try:
        while True:
            output = ['',
                      'Open vStorage - NSM/ABM debug information',
                      '=========================================',
                      'timestamp: {0}'.format(time.time()),
                      '']
            sr_backends = {}
            for _alba_backend in AlbaBackendList.get_albabackends():
                for _abm_service in _alba_backend.abm_services:
                    _storagerouter = _abm_service.service.storagerouter
                    if _storagerouter not in sr_backends:
                        sr_backends[_storagerouter] = []
                    sr_backends[_storagerouter].append(_alba_backend)
            for _sr in StorageRouterList.get_storagerouters():
                output.append('+ {0} ({1})'.format(_sr.name, _sr.ip))
                if _sr in sr_backends:
                    for _alba_backend in sr_backends[_sr]:
                        output.append('  + {0}'.format(_alba_backend.backend.name))
                        for _abm_service in _alba_backend.abm_services:
                            if _abm_service.service.storagerouter_guid == _sr.guid:
                                output.append('    + ABM - port {0}'.format(_abm_service.service.ports[0]))
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
                                output.append('    + NSM {0} - port {1} - capacity: {2}, load: {3}'.format(
                                    _nsm_service.number, _nsm_service.service.ports[0], _service_capacity, _load
                                ))
            output += ['',
                       'Press ^C to exit',
                       '']
            print '\x1b[2J\x1b[H' + '\n'.join(output)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
