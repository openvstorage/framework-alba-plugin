# Copyright 2014 iNuron NV
#
# Licensed under the Open vStorage Modified Apache License (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.openvstorage.org/license
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
AlbaController module
"""

import json
import os
import random
import tempfile
import time
from celery.schedules import crontab
from ovs.celery_run import celery
from ovs.dal.hybrids.albaasd import AlbaASD
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.hybrids.diskpartition import DiskPartition
from ovs.dal.hybrids.j_abmservice import ABMService
from ovs.dal.hybrids.j_nsmservice import NSMService
from ovs.dal.hybrids.service import Service as DalService
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.licenselist import LicenseList
from ovs.dal.lists.servicelist import ServiceList
from ovs.dal.lists.servicetypelist import ServiceTypeList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs.extensions.db.arakoon.ArakoonInstaller import ArakoonClusterConfig
from ovs.extensions.db.arakoon.ArakoonInstaller import ArakoonInstaller
from ovs.extensions.generic.configuration import Configuration
from ovs.extensions.generic.sshclient import SSHClient
from ovs.extensions.generic.sshclient import UnableToConnectException
from ovs.extensions.packages.package import PackageManager
from ovs.extensions.plugins.albacli import AlbaCLI
from ovs.extensions.services.service import ServiceManager
from ovs.lib.helpers.decorators import add_hooks
from ovs.lib.helpers.decorators import ensure_single
from ovs.log.logHandler import LogHandler

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
    def add_preset(alba_backend_guid, name, compression, policies, encryption):
        """
        Adds a preset to Alba
        Args:
            compression: none | snappy | bzip2
            encryption: none | aec-cbc-256
        """
        temp_key_file = None

        alba_backend = AlbaBackend(alba_backend_guid)
        if name in [preset['name'] for preset in alba_backend.presets]:
            raise RuntimeError('Preset name {0} already exists'.format(name))
        logger.debug('Adding preset {0} with compression {1} and policies {2}'.format(name, compression, policies))
        preset = {'compression': compression,
                  'object_checksum': {'default': ['crc-32c'], 'verify_upload': True, 'allowed': [['none'], ['sha-1'], ['crc-32c']]},
                  'osds': ['all'],
                  'fragment_size': 1048576,
                  'policies': policies,
                  'fragment_checksum': ['crc-32c'],
                  'in_use': False,
                  'name': name}

        if encryption in ['aes-cbc-256']:
            encryption_key = ''.join(random.choice(chr(random.randint(32, 126))) for _ in range(32))
            temp_key_file = tempfile.mktemp()
            with open(temp_key_file, 'wb') as temp_file:
                temp_file.write(encryption_key)
                temp_file.flush()
            preset['fragment_encryption'] = ['{0}'.format(encryption), '{0}'.format(temp_key_file)]
        else:
            preset['fragment_encryption'] = ['none']

        config_file = '/opt/OpenvStorage/config/arakoon/{0}/{0}.cfg'.format(alba_backend.backend.name + '-abm')

        temp_config_file = tempfile.mktemp()
        with open(temp_config_file, 'wb') as data_file:
            data_file.write(json.dumps(preset))
            data_file.flush()
            AlbaCLI.run('create-preset', config=config_file, extra_params=[name, '<', data_file.name], as_json=True)
            alba_backend.invalidate_dynamics()
        for filename in [temp_key_file, temp_config_file]:
            if filename and os.path.exists(filename) and os.path.isfile(filename):
                os.remove(filename)

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
    @celery.task(name='alba.update_preset')
    def update_preset(alba_backend_guid, name, policies):
        """
        Updates policies for an existing preset to Alba
        Args:
            alba_backend_guid: guid of backend
            name: name of backend
            policies: new policy list to be sent to alba
        """
        temp_key_file = None

        alba_backend = AlbaBackend(alba_backend_guid)
        logger.debug('Adding preset {0} with policies {1}'.format(name, policies))
        preset = {'policies': policies}

        config_file = '/opt/OpenvStorage/config/arakoon/{0}/{0}.cfg'.format(alba_backend.backend.name + '-abm')

        temp_config_file = tempfile.mktemp()
        with open(temp_config_file, 'wb') as data_file:
            data_file.write(json.dumps(preset))
            data_file.flush()
            AlbaCLI.run('update-preset', config=config_file, extra_params=[name, '<', data_file.name], as_json=True)
            alba_backend.invalidate_dynamics()
        for filename in [temp_key_file, temp_config_file]:
            if filename and os.path.exists(filename) and os.path.isfile(filename):
                os.remove(filename)

    @staticmethod
    @celery.task(name='alba.add_cluster')
    def add_cluster(alba_backend_guid):
        """
        Adds an arakoon cluster to service backend
        """
        AlbaController.manual_alba_arakoon_checkup(alba_backend_guid=alba_backend_guid,
                                                   create_nsm_cluster=True)

        alba_backend = AlbaBackend(alba_backend_guid)
        config_file = '/opt/OpenvStorage/config/arakoon/{0}/{0}.cfg'.format(alba_backend.backend.name + '-abm')
        alba_backend.alba_id = AlbaCLI.run('get-alba-id', config=config_file, as_json=True, attempts=5)['id']
        alba_backend.save()

        lic = LicenseList.get_by_component('alba')
        if lic is not None:
            AlbaController.apply(lic.component, lic.data, lic.signature, alba_backend=alba_backend)

        AlbaController.nsm_checkup()

        # Mark the backend as "running"
        alba_backend.backend.status = 'RUNNING'
        alba_backend.backend.save()

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
        service = None
        client = None
        for abm_service in AlbaBackend(alba_backend_guid).abm_services:
            try:
                service = abm_service.service
                client = SSHClient(service.storagerouter.ip)
            except UnableToConnectException:
                pass
            break
        if client is None or service is None:
            raise RuntimeError('Could load metadata')
        config = ArakoonClusterConfig(service.name)
        config.load_config(client)
        return config.export()

    @staticmethod
    def link_plugins(client, data_dir, plugins, cluster_name):
        data_dir = '' if data_dir == '/' else data_dir
        for plugin in plugins:
            cmd = 'ln -s {0}/{1}.cmxs {2}/arakoon/{3}/db'.format(AlbaController.ARAKOON_PLUGIN_DIR, plugin, data_dir, cluster_name)
            client.run(cmd)

    @staticmethod
    @celery.task(name='alba.scheduled_alba_arakoon_checkup', bind=True, schedule=crontab(minute='45', hour='*'))
    @ensure_single(['alba.scheduled_alba_arakoon_checkup'])
    def scheduled_alba_arakoon_checkup():
        """
        Makes sure the volumedriver arakoon is on all available master nodes
        """
        AlbaController._alba_arakoon_checkup(create_nsm_cluster=False)

    @staticmethod
    @celery.task(name='alba.manual_alba_arakoon_checkup')
    def manual_alba_arakoon_checkup(alba_backend_guid, create_nsm_cluster=False):
        """
        Creates a new Arakoon Cluster if required and extends cluster if possible on all available master nodes
        """
        AlbaController._alba_arakoon_checkup(alba_backend_guid=alba_backend_guid,
                                             create_nsm_cluster=create_nsm_cluster)

    @staticmethod
    def _alba_arakoon_checkup(create_nsm_cluster, alba_backend_guid=None):
        current_ips = {}
        current_services = {}
        abm_service_type = ServiceTypeList.get_by_name('AlbaManager')
        nsm_service_type = ServiceTypeList.get_by_name('NamespaceManager')
        alba_backends = AlbaBackendList.get_albabackends()

        for alba_backend in alba_backends:
            abm_service_name = alba_backend.backend.name + "-abm"
            nsm_service_name = alba_backend.backend.name + "-nsm_0"
            current_ips[alba_backend] = {'abm': [],
                                         'nsm': []}
            current_services[alba_backend] = {'abm': [],
                                              'nsm': []}
            for service in abm_service_type.services:
                if service.name == abm_service_name:
                    current_ips[alba_backend]['abm'].append(service.storagerouter.ip)
                    current_services[alba_backend]['abm'].append(service)
            for service in nsm_service_type.services:
                if service.name == nsm_service_name:
                    current_ips[alba_backend]['nsm'].append(service.storagerouter.ip)
                    current_services[alba_backend]['nsm'].append(service)

        slaves = StorageRouterList.get_slaves()
        masters = StorageRouterList.get_masters()
        clients = {}
        try:
            for storagerouter in masters + slaves:
                clients[storagerouter] = SSHClient(storagerouter)
        except UnableToConnectException:
            raise RuntimeError('Not all StorageRouters are reachable')

        available_storagerouters = {}
        for storagerouter in masters:
            storagerouter.invalidate_dynamics(['partition_config'])
            if len(storagerouter.partition_config[DiskPartition.ROLES.DB]) > 0:
                available_storagerouters[storagerouter] = DiskPartition(storagerouter.partition_config[DiskPartition.ROLES.DB][0])

        if not available_storagerouters:
            raise RuntimeError('Could not find any partitions with DB role')

        if alba_backend_guid is not None:
            storagerouter, partition = available_storagerouters.items()[0]
            alba_backend = AlbaBackend(alba_backend_guid)
            abm_service_name = alba_backend.backend.name + "-abm"
            nsm_service_name = alba_backend.backend.name + "-nsm_0"
            if len(current_services[alba_backend]['abm']) == 0:
                abm_service = AlbaController.create_or_extend_cluster(create=True,
                                                                      client=clients[storagerouter],
                                                                      backend=alba_backend,
                                                                      service=abm_service_type,
                                                                      partition=partition,
                                                                      storagerouter=storagerouter)
                for slave in masters + slaves:
                    ArakoonInstaller.deploy_to_slave(storagerouter.ip, slave.ip, abm_service_name)
                ArakoonInstaller.restart_cluster_add(cluster_name=abm_service_name,
                                                     current_ips=current_ips[alba_backend]['abm'],
                                                     new_ip=storagerouter.ip)
                current_ips[alba_backend]['abm'].append(storagerouter.ip)
                current_services[alba_backend]['abm'].append(abm_service)

            if len(current_services[alba_backend]['nsm']) == 0 and create_nsm_cluster is True:
                nsm_service = AlbaController.create_or_extend_cluster(create=True,
                                                                      client=clients[storagerouter],
                                                                      backend=alba_backend,
                                                                      service=nsm_service_type,
                                                                      partition=partition,
                                                                      storagerouter=storagerouter)
                ArakoonInstaller.restart_cluster_add(cluster_name=nsm_service_name,
                                                     current_ips=current_ips[alba_backend]['nsm'],
                                                     new_ip=storagerouter.ip)
                current_ips[alba_backend]['nsm'].append(storagerouter.ip)
                current_services[alba_backend]['nsm'].append(nsm_service)
                AlbaController.register_nsm(abm_service_name, nsm_service_name, storagerouter.ip)

            AlbaController._setup_service('maintenance', storagerouter.ip, abm_service_name, alba_backend.backend.name)
            AlbaController._setup_service('rebalancer', storagerouter.ip, abm_service_name, alba_backend.backend.name)

        for alba_backend in alba_backends:
            abm_service_name = alba_backend.backend.name + "-abm"
            if 0 < len(current_services[alba_backend]['abm']) < len(available_storagerouters):
                for storagerouter, partition in available_storagerouters.iteritems():
                    if storagerouter.ip in current_ips[alba_backend]['abm']:
                        continue

                    abm_service = AlbaController.create_or_extend_cluster(create=False,
                                                                          client=clients[storagerouter],
                                                                          backend=alba_backend,
                                                                          service=abm_service_type,
                                                                          partition=partition,
                                                                          storagerouter=storagerouter,
                                                                          master_ip=current_ips[alba_backend]['abm'][0])
                    for slave in masters + slaves:
                        ArakoonInstaller.deploy_to_slave(current_ips[alba_backend]['abm'][0], slave.ip, abm_service_name)
                    ArakoonInstaller.restart_cluster_add(cluster_name=alba_backend.backend.name + "-abm",
                                                         current_ips=current_ips[alba_backend]['abm'],
                                                         new_ip=storagerouter.ip)
                    current_ips[alba_backend]['abm'].append(storagerouter.ip)
                    current_services[alba_backend]['abm'].append(abm_service)

                    AlbaController._setup_service('maintenance', storagerouter.ip, abm_service_name, alba_backend.backend.name)
                    AlbaController._setup_service('rebalancer', storagerouter.ip, abm_service_name, alba_backend.backend.name)

    @staticmethod
    @add_hooks('setup', 'extranode')
    def on_extranode(cluster_ip, master_ip=None):
        """
        An extra node is added, make sure it has the alba arakoon client file if possible
        """
        _ = master_ip  # The master_ip will be passed in by caller
        servicetype = ServiceTypeList.get_by_name('AlbaManager')
        for alba_backend in AlbaBackendList.get_albabackends():
            alba_service_name = alba_backend.backend.name + "-abm"
            for service in servicetype.services:
                if service.name == alba_service_name:
                    ArakoonInstaller.deploy_to_slave(service.storagerouter.ip, cluster_ip, alba_service_name)
                    break

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
            logger.info('Shrinking ABM for {0}'.format(alba_backend.backend.name))
            storagerouter_ips = [abm_service.service.storagerouter.ip for abm_service in alba_backend.abm_services]
            service = None
            abm_service = None
            service_name = alba_backend.backend.name + "-abm"
            if cluster_ip in storagerouter_ips:
                storagerouter_ips.remove(cluster_ip)
                abm_service = [abms for abms in alba_backend.abm_services if abms.service.storagerouter.ip == cluster_ip][0]
                service = abm_service.service
                logger.info('* Shrink ABM cluster')
            ArakoonInstaller.shrink_cluster(master_ip, cluster_ip, service_name)
            if ServiceManager.has_service('arakoon-{0}'.format(service_name), client=client) is True:
                ServiceManager.stop_service('arakoon-{0}'.format(service_name), client=client)
                ServiceManager.remove_service('arakoon-{0}'.format(service_name), client=client)

            logger.info('* Restarting ABM')
            ArakoonInstaller.restart_cluster_remove(service_name, storagerouter_ips)
            logger.info('* Remove old ABM node from model')
            if service is not None:
                abm_service.delete()
                service.delete()

            # Stop and delete the ALBA maintenance service on this node
            AlbaController._remove_service('maintenance', client.ip, service_name, alba_backend.backend.name)
            AlbaController._remove_service('rebalancer', client.ip, service_name, alba_backend.backend.name)

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
        nsm_service_type = ServiceTypeList.get_by_name('NamespaceManager')
        safety = Configuration.get('alba.nsm.safety')
        maxload = Configuration.get('alba.nsm.maxload')

        for backend in AlbaBackendList.get_albabackends():
            abm_service_name = backend.abm_services[0].service.name
            logger.debug('Ensuring NSM safety for backend {0}'.format(abm_service_name))
            nsm_groups = {}
            nsm_storagerouter = {}
            nsm_loads = {}
            for abms in backend.abm_services:
                storagerouter = abms.service.storagerouter
                if storagerouter not in nsm_storagerouter:
                    nsm_storagerouter[storagerouter] = 0
            for nsm_service in backend.nsm_services:
                number = nsm_service.number
                if number not in nsm_groups:
                    nsm_groups[number] = []
                    nsm_loads[number] = AlbaController.get_load(nsm_service)
                nsm_groups[number].append(nsm_service)
                storagerouter = nsm_service.service.storagerouter
                if storagerouter not in nsm_storagerouter:
                    nsm_storagerouter[storagerouter] = 0
                nsm_storagerouter[storagerouter] += 1
            clients = {}
            try:
                for sr in nsm_storagerouter.keys():
                    clients[sr] = SSHClient(sr)
            except UnableToConnectException:
                raise RuntimeError('Not all StorageRouters are reachable')

            # Safety
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
                    nsm_service_name = current_nsm.service.name
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
                        if candidate_sr is None or candidate_load is None:
                            raise RuntimeError('Could not determine a candidate storagerouter')
                        current_srs.append(candidate_sr)
                        available_srs.remove(candidate_sr)
                        # Extend the cluster (configuration, services, ...)
                        logger.debug('  Extending cluster config')
                        candidate_sr.invalidate_dynamics(['partition_config'])
                        partition = DiskPartition(candidate_sr.partition_config[DiskPartition.ROLES.DB][0])
                        nsm_result = ArakoonInstaller.extend_cluster(master_ip=current_nsm.service.storagerouter.ip,
                                                                     new_ip=candidate_sr.ip,
                                                                     cluster_name=nsm_service_name,
                                                                     exclude_ports=ServiceList.get_ports_for_ip(candidate_sr.ip),
                                                                     base_dir=partition.folder)
                        logger.debug('  Linking plugin')
                        AlbaController.link_plugins(client=clients[candidate_sr],
                                                    data_dir=partition.folder,
                                                    plugins=[AlbaController.NSM_PLUGIN],
                                                    cluster_name=nsm_service_name)
                        logger.debug('  Model services')
                        AlbaController._model_service(service_name=nsm_service_name,
                                                      service_type=nsm_service_type,
                                                      ports=[nsm_result['client_port'], nsm_result['messaging_port']],
                                                      storagerouter=candidate_sr,
                                                      junction_type=NSMService,
                                                      backend=backend,
                                                      number=current_nsm.number)
                        logger.debug('  Restart sequence')
                        ArakoonInstaller.restart_cluster_add(cluster_name=nsm_service_name,
                                                             current_ips=[sr.ip for sr in current_srs],
                                                             new_ip=candidate_sr.ip)
                        AlbaController.update_nsm(abm_name=abm_service_name,
                                                  nsm_name=nsm_service_name,
                                                  ip=candidate_sr.ip)
                        logger.debug('Node added')

            # Load
            if min(nsm_loads.values()) >= maxload:
                maxnumber = max(nsm_loads.keys())
                logger.debug('NSM overloaded, adding new NSM')
                # On of the this NSMs node is overloaded. This means the complete NSM is considered overloaded
                # Figure out which StorageRouters are the least occupied
                loads = sorted(nsm_storagerouter.values())[:safety]
                storagerouters = []
                for storagerouter in nsm_storagerouter:
                    if nsm_storagerouter[storagerouter] in loads:
                        storagerouters.append(storagerouter)
                    if len(storagerouters) == safety:
                        break
                # Creating a new NSM cluster
                maxnumber += 1
                nsm_name = '{0}-nsm_{1}'.format(backend.backend.name, maxnumber)
                first_ip = None
                for storagerouter in storagerouters:
                    storagerouter.invalidate_dynamics(['partition_config'])
                    partition = DiskPartition(storagerouter.partition_config[DiskPartition.ROLES.DB][0])
                    if first_ip is None:
                        nsm_result = ArakoonInstaller.create_cluster(cluster_name=nsm_name,
                                                                     ip=storagerouter.ip,
                                                                     exclude_ports=ServiceList.get_ports_for_ip(storagerouter.ip),
                                                                     base_dir=partition.folder,
                                                                     plugins=AlbaController.NSM_PLUGIN)
                        AlbaController.link_plugins(client=clients[storagerouter],
                                                    data_dir=partition.folder,
                                                    plugins=[AlbaController.NSM_PLUGIN],
                                                    cluster_name=nsm_name)
                        AlbaController._model_service(service_name=nsm_name,
                                                      service_type=nsm_service_type,
                                                      ports=[nsm_result['client_port'], nsm_result['messaging_port']],
                                                      storagerouter=storagerouter,
                                                      junction_type=NSMService,
                                                      backend=backend,
                                                      number=maxnumber)
                        first_ip = storagerouter.ip
                    else:
                        nsm_result = ArakoonInstaller.extend_cluster(master_ip=first_ip,
                                                                     new_ip=storagerouter.ip,
                                                                     cluster_name=nsm_name,
                                                                     exclude_ports=ServiceList.get_ports_for_ip(storagerouter.ip),
                                                                     base_dir=partition.folder)
                        AlbaController.link_plugins(client=clients[storagerouter],
                                                    data_dir=partition.folder,
                                                    plugins=[AlbaController.NSM_PLUGIN],
                                                    cluster_name=nsm_name)
                        AlbaController._model_service(service_name=nsm_name,
                                                      service_type=nsm_service_type,
                                                      ports=[nsm_result['client_port'], nsm_result['messaging_port']],
                                                      storagerouter=storagerouter,
                                                      junction_type=NSMService,
                                                      backend=backend,
                                                      number=maxnumber)
                for storagerouter in storagerouters:
                    client = SSHClient(storagerouter, username='root')
                    ArakoonInstaller.start(nsm_name, client)
                AlbaController.register_nsm(abm_name=abm_service_name,
                                            nsm_name=nsm_name,
                                            ip=storagerouters[0].ip)
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
        client = SSHClient(ip)
        if ArakoonInstaller.wait_for_cluster(nsm_name, client) and ArakoonInstaller.wait_for_cluster(abm_name, client):
            AlbaCLI.run('add-nsm-host', config=abm_config_file, extra_params=nsm_config_file, client=client)

    @staticmethod
    def update_nsm(abm_name, nsm_name, ip):
        nsm_config_file = ArakoonInstaller.ARAKOON_CONFIG_FILE.format(nsm_name)
        abm_config_file = ArakoonInstaller.ARAKOON_CONFIG_FILE.format(abm_name)
        client = SSHClient(ip)
        if ArakoonInstaller.wait_for_cluster(nsm_name, client) and ArakoonInstaller.wait_for_cluster(abm_name, client):
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
    def create_or_extend_cluster(create, client, backend, service, partition, storagerouter, master_ip=None):
        if service.name == 'AlbaManager':
            number = None
            plugins = [AlbaController.ABM_PLUGIN]
            service_name = backend.backend.name + "-abm"
            junction_type = ABMService
        else:
            number = 0
            plugins = [AlbaController.NSM_PLUGIN]
            service_name = backend.backend.name + "-nsm_0"
            junction_type = NSMService

        if create is True:
            result = ArakoonInstaller.create_cluster(cluster_name=service_name,
                                                     ip=storagerouter.ip,
                                                     exclude_ports=ServiceList.get_ports_for_ip(storagerouter.ip),
                                                     base_dir=partition.folder,
                                                     plugins=plugins)
        else:
            result = ArakoonInstaller.extend_cluster(master_ip=master_ip,
                                                     new_ip=storagerouter.ip,
                                                     cluster_name=service_name,
                                                     exclude_ports=ServiceList.get_ports_for_ip(storagerouter.ip),
                                                     base_dir=partition.folder)
        AlbaController.link_plugins(client=client,
                                    data_dir=partition.folder,
                                    plugins=plugins,
                                    cluster_name=service_name)
        new_service = AlbaController._model_service(service_name=service_name,
                                                    service_type=service,
                                                    ports=[result['client_port'], result['messaging_port']],
                                                    storagerouter=storagerouter,
                                                    junction_type=junction_type,
                                                    backend=backend,
                                                    number=number)
        return new_service

    @staticmethod
    @add_hooks('update', 'metadata')
    def get_metadata_sdm(client):
        """
        Retrieve information about the SDM packages
        :param client: SSHClient on which to retrieve the metadata
        :return: List of dictionaries which contain services to restart,
                                                    packages to update,
                                                    information about potential downtime
                                                    information about unmet prerequisites
        """
        other_storage_router_ips = [sr.ip for sr in StorageRouterList.get_storagerouters() if sr.ip != client.ip]
        version = ''
        for node in AlbaNodeList.get_albanodes():
            if node.ip in other_storage_router_ips:
                continue
            try:
                candidate = node.client.get_update_information()
                if candidate.get('version'):
                    version = candidate['version']
                    break
            except ValueError as ve:
                if 'No JSON object could be decoded' in ve.message:
                    version = 'Remote ASD'
        return {'framework': [{'name': 'openvstorage-sdm',
                               'version': version,
                               'services': [],
                               'packages': [],
                               'downtime': [],
                               'namespace': 'alba',
                               'prerequisites': []}]}

    @staticmethod
    @add_hooks('update', 'metadata')
    def get_metadata_alba(client):
        """
        Retrieve ALBA packages and services which ALBA depends upon
        Also check the arakoon clusters to be able to warn the customer for potential downtime
        :param client: SSHClient on which to retrieve the metadata
        :return: List of dictionaries which contain services to restart,
                                                    packages to update,
                                                    information about potential downtime
                                                    information about unmet prerequisites
        """
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
                                                          services=['watcher-framework', 'memcached'],
                                                          client=client)
        alba_info = PackageManager.verify_update_required(packages=['alba'],
                                                          services=list(alba_services),
                                                          client=client)
        arakoon_info = PackageManager.verify_update_required(packages=['arakoon'],
                                                             services=list(arakoon_cluster_services),
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
                               'services': [],
                               'packages': arakoon_info['packages'],
                               'downtime': downtime,
                               'namespace': 'alba',
                               'prerequisites': []}]}

    @staticmethod
    @add_hooks('update', 'postupgrade')
    def upgrade_sdm(client):
        """
        Upgrade the openvstorage-sdm packages
        :param client: IP of 1 of the master nodes (On which the update is initiated)
        :return: None
        """
        other_storage_router_ips = [sr.ip for sr in StorageRouterList.get_storagerouters() if sr.ip != client.ip]
        for node in AlbaNodeList.get_albanodes():
            if node.ip in other_storage_router_ips:
                continue

            logger.info('{0}: Upgrading SDM'.format(node.ip))
            counter = 0
            max_counter = 12
            status = 'started'
            while True and counter < max_counter:
                counter += 1
                try:
                    status = node.client.execute_update(status).get('status')
                    if status == 'done':
                        break
                except Exception as ex:
                    logger.warning('Attempt {0} to update SDM failed, trying again'.format(counter))
                    if counter == max_counter:
                        logger.error('{0}: Error during update: {1}'.format(node.ip, ex.message))
                    time.sleep(10)
            if status != 'done':
                logger.error('{0}: Failed to perform SDM update. Please check /var/log/upstart/alba-asdmanager.log on the appropriate node'.format(node.ip))
                raise Exception('Status after upgrade is "{0}"'.format(status))
            node.client.restart_services()

    @staticmethod
    @add_hooks('update', 'postupgrade')
    def restart_arakoon_clusters(client):
        """
        Restart all arakoon clusters after arakoon and/or alba package upgrade
        :param client: IP of 1 of the master nodes (On which the update is initiated)
        :return: None
        """
        services = []
        for alba_backend in AlbaBackendList.get_albabackends():
            services.append('arakoon-{0}'.format(alba_backend.abm_services[0].service.name))
            services.extend(list(set(['arakoon-{0}'.format(service.service.name) for service in alba_backend.nsm_services])))

        info = PackageManager.verify_update_required(packages=['arakoon'],
                                                     services=services,
                                                     client=client)
        for service in info['services']:
            cluster_name = service.lstrip('arakoon-')
            logger.info('Restarting cluster {0}'.format(cluster_name), print_msg=True)
            ArakoonInstaller.restart_cluster(cluster_name=cluster_name,
                                             master_ip=client.ip)
        else:  # In case no arakoon clusters are restarted, we check if alba has been updated and still restart clusters
            proxies = []
            this_sr = StorageRouterList.get_by_ip(client.ip)
            for sr in StorageRouterList.get_storagerouters():
                for service in sr.services:
                    if service.type.name == 'AlbaProxy' and service.storagerouter_guid == this_sr.guid:
                        proxies.append(service.name)
            if proxies:
                info = PackageManager.verify_update_required(packages=['alba'],
                                                             services=proxies,
                                                             client=client)
                if info['services']:
                    for service in services:
                        cluster_name = service.lstrip('arakoon-')
                        logger.info('Restarting cluster {0} because of ALBA update'.format(cluster_name), print_msg=True)
                        ArakoonInstaller.restart_cluster(cluster_name=cluster_name,
                                                         master_ip=client.ip)

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
            'log_level': 'info',
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
