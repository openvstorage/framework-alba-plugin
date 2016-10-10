# Copyright (C) 2016 iNuron NV
#
# This file is part of Open vStorage Open Source Edition (OSE),
# as available from
#
#      http://www.openvstorage.org and
#      http://www.openvstorage.com.
#
# This file is free software; you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License v3 (GNU AGPLv3)
# as published by the Free Software Foundation, in version 3 as it comes
# in the LICENSE.txt file of the Open vStorage OSE distribution.
#
# Open vStorage is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY of any kind.

"""
AlbaController module
"""

import os
import json
import time
import string
import random
import requests
import tempfile
from celery.schedules import crontab
from ConfigParser import RawConfigParser
from StringIO import StringIO
from ovs.celery_run import celery
from ovs.dal.hybrids.albaosd import AlbaOSD
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.albadisk import AlbaDisk
from ovs.dal.hybrids.diskpartition import DiskPartition
from ovs.dal.hybrids.j_abmservice import ABMService
from ovs.dal.hybrids.j_nsmservice import NSMService
from ovs.dal.hybrids.service import Service as DalService
from ovs.dal.hybrids.servicetype import ServiceType
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.servicetypelist import ServiceTypeList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs.extensions.api.client import OVSClient
from ovs.extensions.db.arakoon.ArakoonInstaller import ArakoonClusterConfig, ArakoonInstaller
from ovs.extensions.generic.configuration import Configuration
from ovs.extensions.generic.sshclient import SSHClient, UnableToConnectException
from ovs.extensions.packages.package import PackageManager
from ovs.extensions.plugins.albacli import AlbaCLI
from ovs.extensions.services.service import ServiceManager
from ovs.lib.helpers.decorators import add_hooks, ensure_single
from ovs.lib.helpers.toolbox import Toolbox
from ovs.log.log_handler import LogHandler


class AlbaController(object):
    """
    Contains all BLL related to ALBA
    """
    ABM_PLUGIN = 'albamgr_plugin'
    NSM_PLUGIN = 'nsm_host_plugin'
    ARAKOON_PLUGIN_DIR = '/usr/lib/alba'
    ALBA_MAINTENANCE_SERVICE_PREFIX = 'alba-maintenance'
    ALBA_REBALANCER_SERVICE_PREFIX = 'alba-rebalancer'
    CONFIG_ALBA_BACKEND_KEY = '/ovs/alba/backends/{0}'
    CONFIG_DEFAULT_NSM_HOSTS_KEY = CONFIG_ALBA_BACKEND_KEY.format('default_nsm_hosts')
    NR_OF_AGENTS_CONFIG_KEY = '/ovs/alba/backends/{0}/maintenance/nr_of_agents'

    _logger = LogHandler.get('lib', name='alba')

    @staticmethod
    def get_abm_service_name(backend):
        """
        :param backend: The backend for which the ABM name should be returned
        :type backend: Backend

        :return: The ABM name
        :rtype: str
        """
        return backend.alba_backend.abm_services[0].service.name if len(backend.alba_backend.abm_services) > 0 else backend.name + '-abm'

    @staticmethod
    def get_nsm_service_name(backend):
        """
        :param backend: The backend for which the NSM name should be returned
        :type backend: Backend

        :return: The NSM name
        :rtype: str
        """
        return backend.alba_backend.nsm_services[0].service.name if len(backend.alba_backend.nsm_services) > 0 else backend.name + '-nsm_0'

    @staticmethod
    @celery.task(name='alba.add_units')
    def add_units(alba_backend_guid, osds, metadata=None):
        """
        Adds storage units to an Alba backend
        :param alba_backend_guid: Guid of the ALBA backend
        :type alba_backend_guid: str

        :param osds: ASDs to add to the ALBA backend
        :type osds: dict

        :param metadata: Metadata to add to the OSD (connection information for remote backend, general backend information)
        :type metadata: dict

        :return: None
        """
        alba_backend = AlbaBackend(alba_backend_guid)
        config = Configuration.get_configuration_path('/ovs/arakoon/{0}/config'.format(AlbaController.get_abm_service_name(backend=alba_backend.backend)))
        disks = {}

        for osd_id, disk_guid in osds.iteritems():
            if disk_guid is not None and disk_guid not in disks:
                disks[disk_guid] = AlbaDisk(disk_guid)
            alba_disk = disks.get(disk_guid)
            AlbaCLI.run(command='claim-osd', config=config, long_id=osd_id, to_json=True)
            osd = AlbaOSD()
            osd.osd_id = osd_id
            osd.osd_type = AlbaOSD.OSD_TYPES.ALBA_BACKEND if alba_disk is None else AlbaOSD.OSD_TYPES.ASD
            osd.metadata = metadata
            osd.alba_disk = alba_disk
            osd.alba_backend = alba_backend
            osd.save()
        alba_backend.invalidate_dynamics()
        alba_backend.backend.invalidate_dynamics()

    @staticmethod
    @celery.task(name='alba.remove_units')
    def remove_units(alba_backend_guid, osd_ids):
        """
        Removes storage units from an Alba backend
        :param alba_backend_guid: Guid of the ALBA backend
        :type alba_backend_guid: str

        :param osd_ids: IDs of the ASDs
        :type osd_ids: list

        :param absorb_exception: Ignore potential errors
        :type absorb_exception: bool

        :return: None
        """
        alba_backend = AlbaBackend(alba_backend_guid)
        config = Configuration.get_configuration_path('/ovs/arakoon/{0}/config'.format(AlbaController.get_abm_service_name(backend=alba_backend.backend)))
        failed_osds = []
        last_exception = None
        for osd_id in osd_ids:
            try:
                AlbaCLI.run(command='purge-osd', config=config, long_id=osd_id, to_json=True)
            except Exception as ex:
                AlbaController._logger.exception('Error purging OSD {0}'.format(osd_id))
                last_exception = ex
                failed_osds.append(osd_id)
        if len(failed_osds) > 0:
            if len(osd_ids) == 1:
                raise last_exception
            raise RuntimeError('Error processing one or more OSDs: {0}'.format(failed_osds))

    @staticmethod
    @celery.task(name='alba.add_preset')
    def add_preset(alba_backend_guid, name, compression, policies, encryption, fragment_size=None):
        """
        Adds a preset to Alba
        :param alba_backend_guid: Guid of the ALBA backend
        :type alba_backend_guid: str

        :param name: Name of the preset
        :type name: str

        :param compression: Compression type for the preset (none | snappy | bzip2)
        :type compression: str

        :param policies: Policies for the preset
        :type policies: list

        :param encryption: Encryption for the preset (none | aec-cbc-256)
        :type encryption: str

        :param fragment_size: Size of a fragment in bytes (e.g. 1048576)
        :type fragment_size: int

        :return: None
        """
        temp_key_file = None

        alba_backend = AlbaBackend(alba_backend_guid)
        if name in [preset['name'] for preset in alba_backend.presets]:
            raise RuntimeError('Preset name {0} already exists'.format(name))

        if fragment_size is None:
            fragment_size = 1048576  # default value is 1 MB
        else:
            try:
                fragment_size = int(fragment_size)
            except ValueError:
                fragment_size = 1048576

        AlbaController._logger.debug('Adding preset {0} with compression {1} and policies {2}'.format(name, compression, policies))
        preset = {'compression': compression,
                  'object_checksum': {'default': ['crc-32c'],
                                      'verify_upload': True,
                                      'allowed': [['none'], ['sha-1'], ['crc-32c']]},
                  'osds': ['all'],
                  'fragment_size': fragment_size,
                  'policies': policies,
                  'fragment_checksum': ['crc-32c'],
                  'fragment_encryption': ['none'],
                  'in_use': False,
                  'name': name}

        if encryption in ['aes-cbc-256']:
            encryption_key = ''.join(random.choice(chr(random.randint(32, 126))) for _ in range(32))
            temp_key_file = tempfile.mktemp()
            with open(temp_key_file, 'wb') as temp_file:
                temp_file.write(encryption_key)
                temp_file.flush()
            preset['fragment_encryption'] = ['{0}'.format(encryption), '{0}'.format(temp_key_file)]

        config = Configuration.get_configuration_path('/ovs/arakoon/{0}/config'.format(AlbaController.get_abm_service_name(backend=alba_backend.backend)))
        temp_config_file = tempfile.mktemp()
        with open(temp_config_file, 'wb') as data_file:
            data_file.write(json.dumps(preset))
            data_file.flush()
        AlbaCLI.run(command='create-preset', config=config, to_json=True, input_url=temp_config_file, extra_params=[name])
        alba_backend.invalidate_dynamics()
        for filename in [temp_key_file, temp_config_file]:
            if filename and os.path.exists(filename) and os.path.isfile(filename):
                os.remove(filename)

    @staticmethod
    @celery.task(name='alba.delete_preset')
    def delete_preset(alba_backend_guid, name):
        """
        Deletes a preset from the Alba backend
        :param alba_backend_guid: Guid of the ALBA backend
        :type alba_backend_guid: str

        :param name: Name of the preset
        :type name: str

        :return: None
        """
        alba_backend = AlbaBackend(alba_backend_guid)
        AlbaController._logger.debug('Deleting preset {0}'.format(name))
        config = Configuration.get_configuration_path('/ovs/arakoon/{0}/config'.format(AlbaController.get_abm_service_name(backend=alba_backend.backend)))
        AlbaCLI.run(command='delete-preset', config=config, to_json=True, extra_params=[name])
        alba_backend.invalidate_dynamics()

    @staticmethod
    @celery.task(name='alba.update_preset')
    def update_preset(alba_backend_guid, name, policies):
        """
        Updates policies for an existing preset to Alba
        :param alba_backend_guid: Guid of the ALBA backend
        :type alba_backend_guid: str

        :param name: Name of backend
        :type name: str

        :param policies: New policy list to be sent to alba
        :type policies: list

        :return: None
        """
        temp_key_file = None

        alba_backend = AlbaBackend(alba_backend_guid)
        AlbaController._logger.debug('Adding preset {0} with policies {1}'.format(name, policies))
        preset = {'policies': policies}

        config = Configuration.get_configuration_path('/ovs/arakoon/{0}/config'.format(AlbaController.get_abm_service_name(backend=alba_backend.backend)))
        temp_config_file = tempfile.mktemp()
        with open(temp_config_file, 'wb') as data_file:
            data_file.write(json.dumps(preset))
            data_file.flush()
        AlbaCLI.run(command='update-preset', config=config, to_json=True, input_url=temp_config_file, extra_params=[name])
        alba_backend.invalidate_dynamics()
        for filename in [temp_key_file, temp_config_file]:
            if filename and os.path.exists(filename) and os.path.isfile(filename):
                os.remove(filename)

    @staticmethod
    @celery.task(name='alba.add_cluster')
    def add_cluster(alba_backend_guid):
        """
        Adds an arakoon cluster to service backend
        :param alba_backend_guid: Guid of the ALBA backend
        :type alba_backend_guid: str

        :return: None
        """
        from ovs.lib.albanodecontroller import AlbaNodeController

        try:
            AlbaController.manual_alba_arakoon_checkup(alba_backend_guid=alba_backend_guid,
                                                       create_nsm_cluster=True)
        except Exception as ex:
            AlbaController._logger.exception('Failed manual Alba Arakoon checkup during add cluster for backend {0}. {1}'.format(alba_backend_guid, ex))
            AlbaController.remove_cluster(alba_backend_guid=alba_backend_guid)
            raise

        alba_backend = AlbaBackend(alba_backend_guid)
        config = Configuration.get_configuration_path('/ovs/arakoon/{0}/config'.format(AlbaController.get_abm_service_name(backend=alba_backend.backend)))
        alba_backend.alba_id = AlbaCLI.run(command='get-alba-id', config=config, to_json=True, attempts=5)['id']
        alba_backend.save()
        if not Configuration.exists(AlbaController.CONFIG_DEFAULT_NSM_HOSTS_KEY):
            Configuration.set(AlbaController.CONFIG_DEFAULT_NSM_HOSTS_KEY, 1)
        nsms = max(1, Configuration.get(AlbaController.CONFIG_DEFAULT_NSM_HOSTS_KEY))
        try:
            AlbaController.nsm_checkup(backend_guid=alba_backend.guid, min_nsms=nsms)
        except Exception as ex:
            AlbaController._logger.exception('Failed NSM checkup during add cluster for backend {0}. {1}'.format(alba_backend.guid, ex))
            AlbaController.remove_cluster(alba_backend_guid=alba_backend.guid)
            raise

        # Enable LRU
        masters = StorageRouterList.get_masters()
        redis_endpoint = 'redis://{0}:6379/alba_lru_{1}'.format(masters[0].ip, alba_backend.guid)
        AlbaCLI.run(command='update-maintenance-config', config=config, set_lru_cache_eviction=redis_endpoint)

        # Mark the backend as "running"
        alba_backend.backend.status = 'RUNNING'
        alba_backend.backend.save()

        AlbaNodeController.model_local_albanode()
        AlbaController.checkup_maintenance_agents.delay()

    @staticmethod
    @celery.task(name='alba.remove_cluster')
    def remove_cluster(alba_backend_guid):
        """
        Removes an Alba backend/cluster
        :param alba_backend_guid: Guid of the ALBA backend
        :type alba_backend_guid: str

        :return: None
        """

        albabackend = AlbaBackend(alba_backend_guid)
        if len(albabackend.osds) > 0:
            raise RuntimeError('A backend with claimed OSDs cannot be removed')

        # openvstorage nodes
        for abm_service in albabackend.abm_services:
            if abm_service.service.is_internal is True:
                test_ip = abm_service.service.storagerouter.ip
                try:
                    SSHClient(test_ip, username='root')
                except UnableToConnectException as uc:
                    raise RuntimeError('Node {0} is not reachable, backend cannot be removed. {1}'.format(test_ip, uc))

        # storage nodes
        for alba_node in AlbaNodeList.get_albanodes():
            try:
                alba_node.client.list_maintenance_services()
            except requests.exceptions.ConnectionError as ce:
                raise RuntimeError('Node {0} is not reachable, backend cannot be removed. {1}'.format(alba_node.ip, ce))

        AlbaController._logger.debug('Removing ALBA backend "{0}"'.format(albabackend.name))
        for service_type, services in {'abm': albabackend.abm_services, 'nsm': albabackend.nsm_services}.iteritems():
            AlbaController._logger.debug('Removing {0} services of type "{1}"'.format(len(services), service_type))
            cluster_removed = []
            for ser in services:
                service = ser.service
                if service.name not in cluster_removed:
                    cluster_removed.append(service.name)
                    if service.is_internal is True:
                        AlbaController._logger.debug('Deleting arakoon cluster "{0}"'.format(service.name))
                        ArakoonInstaller.delete_cluster(service.name, service.storagerouter.ip)
                        AlbaController._logger.debug('Deleted arakoon cluster "{0}"'.format(service.name))
                    else:
                        AlbaController._logger.debug('Unclaiming arakoon cluster "{0}"'.format(service.name))
                        ArakoonInstaller.unclaim_externally_managed_cluster(cluster_name=service.name)
                        AlbaController._logger.debug('Unclaimed arakoon cluster "{0}"'.format(service.name))
                AlbaController._logger.debug('Removing service "{0}"'.format(service.name))
                ser.delete()
                service.delete()
                AlbaController._logger.debug('Removed service "{0}"'.format(service.name))

        # Removing maintenance agents
        for node in AlbaNodeList.get_albanodes():
            try:
                for service_name in node.client.list_maintenance_services():
                    backend_name = service_name.split('_', 1)[1].rsplit('-', 1)[0]  # E.g. alba-maintenance_mybackend-a4f7e3c61
                    if backend_name == albabackend.name:
                        node.client.remove_maintenance_service(service_name)
                        AlbaController._logger.info('Removed maintenance service {0} on {1}'.format(service_name, node.ip))
            except Exception as ex:
                AlbaController._logger.exception('Could not clean up maintenance services for {0}'.format(albabackend.name))

        config_key = AlbaController.CONFIG_ALBA_BACKEND_KEY.format(alba_backend_guid)
        AlbaController._logger.debug('Deleting ALBA backend entry "{0}" from Configuration'.format(config_key))
        Configuration.delete(config_key)

        AlbaController._logger.debug('Deleting ALBA backend from model')
        backend = albabackend.backend
        for junction in list(backend.domains):
            junction.delete()
        albabackend.delete()
        backend.delete()

    @staticmethod
    @celery.task(name='alba.get_arakoon_config')
    def get_arakoon_config(alba_backend_guid):
        """
        Gets the arakoon configuration for an Alba backend
        :param alba_backend_guid: Guid of the ALBA backend
        :type alba_backend_guid: str

        :return: Arakoon cluster configuration information
        :rtype: dict
        """
        service = None
        client = None
        for abm_service in AlbaBackend(alba_backend_guid).abm_services:
            service = abm_service.service
            if service.is_internal is True:
                try:
                    client = SSHClient(service.storagerouter.ip)
                    break
                except UnableToConnectException:
                    pass
        if service is None or (client is None and service.is_internal is True):
            raise RuntimeError('Could not load arakoon configuration')
        config = ArakoonClusterConfig(cluster_id=service.name, filesystem=False)
        config.load_config()
        return config.export()

    @staticmethod
    def link_plugins(client, data_dir, plugins, cluster_name):
        """
        Create symlinks for the arakoon plugins to the correct (mounted) partition
        :param client: SSHClient to execute this on
        :type client: SSHClient

        :param data_dir: Directory on which the DB partition resides
        :type data_dir: str

        :param plugins: Plugins to symlink
        :type plugins: list

        :param cluster_name: Name of the arakoon cluster
        :type cluster_name: str

        :return: None
        """
        data_dir = '' if data_dir == '/' else data_dir
        for plugin in plugins:
            cmd = 'ln -s {0}/{1}.cmxs {2}/arakoon/{3}/db'.format(AlbaController.ARAKOON_PLUGIN_DIR, plugin, data_dir, cluster_name)
            client.run(cmd)

    @staticmethod
    @celery.task(name='alba.scheduled_alba_arakoon_checkup', schedule=crontab(minute='30', hour='*'))
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
        :param alba_backend_guid: Guid of the ALBA backend
        :type alba_backend_guid: str

        :param create_nsm_cluster: Create the NSM cluster if not present yet
        :type create_nsm_cluster: bool

        :return: None
        """
        AlbaController._alba_arakoon_checkup(alba_backend_guid=alba_backend_guid,
                                             create_nsm_cluster=create_nsm_cluster)

    @staticmethod
    @ensure_single(task_name='alba.alba_arakoon_checkup')
    def _alba_arakoon_checkup(create_nsm_cluster, alba_backend_guid=None):
        slaves = StorageRouterList.get_slaves()
        masters = StorageRouterList.get_masters()
        clients = {}
        for storagerouter in masters + slaves:
            try:
                clients[storagerouter] = SSHClient(storagerouter)
            except UnableToConnectException:
                AlbaController._logger.warning("Storage Router with IP {0} is not reachable".format(storagerouter.ip))

        abm_service_type = ServiceTypeList.get_by_name(ServiceType.SERVICE_TYPES.ALBA_MGR)
        nsm_service_type = ServiceTypeList.get_by_name(ServiceType.SERVICE_TYPES.NS_MGR)
        alba_backends = AlbaBackendList.get_albabackends()

        current_ips = {}
        current_services = {}
        for alba_backend in alba_backends:
            current_ips[alba_backend] = {'abm': [],
                                         'nsm': []}
            current_services[alba_backend] = {'abm': [],
                                              'nsm': []}
            for service in abm_service_type.services:
                if service.name == AlbaController.get_abm_service_name(backend=alba_backend.backend):
                    current_services[alba_backend]['abm'].append(service)
                    if service.is_internal is True:
                        current_ips[alba_backend]['abm'].append(service.storagerouter.ip)
            for service in nsm_service_type.services:
                if service.name == AlbaController.get_nsm_service_name(backend=alba_backend.backend):
                    current_services[alba_backend]['nsm'].append(service)
                    if service.is_internal is True:
                        current_ips[alba_backend]['nsm'].append(service.storagerouter.ip)

        available_storagerouters = {}
        for storagerouter in masters:
            if storagerouter in clients:
                storagerouter.invalidate_dynamics(['partition_config'])
                if len(storagerouter.partition_config[DiskPartition.ROLES.DB]) > 0:
                    available_storagerouters[storagerouter] = DiskPartition(storagerouter.partition_config[DiskPartition.ROLES.DB][0])

        # Cluster creation
        if alba_backend_guid is not None:
            alba_backend = AlbaBackend(alba_backend_guid)
            abm_service_name = AlbaController.get_abm_service_name(backend=alba_backend.backend)

            # ABM arakoon cluster creation
            if len(current_services[alba_backend]['abm']) == 0:
                metadata = ArakoonInstaller.get_unused_arakoon_metadata_and_claim(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.ABM)
                if metadata is None:  # No externally unused clusters found, we create 1 ourselves
                    if not available_storagerouters:
                        raise RuntimeError('Could not find any partitions with DB role')
                    AlbaController._logger.info('Creating arakoon cluster: {0}'.format(abm_service_name))
                    storagerouter, partition = available_storagerouters.items()[0]
                    result = ArakoonInstaller.create_cluster(cluster_name=abm_service_name,
                                                             cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.ABM,
                                                             ip=storagerouter.ip,
                                                             base_dir=partition.folder,
                                                             plugins=[AlbaController.ABM_PLUGIN])
                    AlbaController.link_plugins(client=clients[storagerouter],
                                                data_dir=partition.folder,
                                                plugins=[AlbaController.ABM_PLUGIN],
                                                cluster_name=abm_service_name)
                    ArakoonInstaller.restart_cluster_add(cluster_name=abm_service_name,
                                                         current_ips=current_ips[alba_backend]['abm'],
                                                         new_ip=storagerouter.ip,
                                                         filesystem=False)
                    ArakoonInstaller.claim_cluster(cluster_name=abm_service_name,
                                                   master_ip=storagerouter.ip,
                                                   filesystem=False,
                                                   metadata=result['metadata'])
                    current_ips[alba_backend]['abm'].append(storagerouter.ip)
                    ports = [result['client_port'], result['messaging_port']]
                    metadata = result['metadata']
                else:
                    ports = []
                    storagerouter = None

                abm_service_name = metadata['cluster_name']
                AlbaController._logger.info('Claimed {0} managed arakoon cluster: {1}'.format('externally' if storagerouter is None else 'internally', abm_service_name))
                AlbaController._update_abm_client_config(abm_name=abm_service_name,
                                                         ip=clients.keys()[0].ip)
                abm_service = AlbaController._model_service(service_name=abm_service_name,
                                                            service_type=abm_service_type,
                                                            ports=ports,
                                                            storagerouter=storagerouter,
                                                            junction_type=ABMService,
                                                            backend=alba_backend)
                current_services[alba_backend]['abm'].append(abm_service)

            # NSM arakoon cluster creation
            if len(current_services[alba_backend]['nsm']) == 0 and create_nsm_cluster is True:
                metadata = ArakoonInstaller.get_unused_arakoon_metadata_and_claim(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM)
                if metadata is None:  # No externally unused clusters found, we create 1 ourselves
                    if not available_storagerouters:
                        raise RuntimeError('Could not find any partitions with DB role')
                    nsm_service_name = AlbaController.get_nsm_service_name(backend=alba_backend.backend)
                    AlbaController._logger.info('Creating arakoon cluster: {0}'.format(nsm_service_name))
                    storagerouter, partition = available_storagerouters.items()[0]
                    result = ArakoonInstaller.create_cluster(cluster_name=nsm_service_name,
                                                             cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM,
                                                             ip=storagerouter.ip,
                                                             base_dir=partition.folder,
                                                             plugins=[AlbaController.NSM_PLUGIN])
                    AlbaController.link_plugins(client=clients[storagerouter],
                                                data_dir=partition.folder,
                                                plugins=[AlbaController.NSM_PLUGIN],
                                                cluster_name=nsm_service_name)
                    ArakoonInstaller.restart_cluster_add(cluster_name=nsm_service_name,
                                                         current_ips=current_ips[alba_backend]['nsm'],
                                                         new_ip=storagerouter.ip,
                                                         filesystem=False)
                    ArakoonInstaller.claim_cluster(cluster_name=nsm_service_name,
                                                   master_ip=storagerouter.ip,
                                                   filesystem=False,
                                                   metadata=result['metadata'])
                    current_ips[alba_backend]['nsm'].append(storagerouter.ip)
                    ports = [result['client_port'], result['messaging_port']]
                    metadata = result['metadata']
                else:
                    ports = []
                    storagerouter = None

                nsm_service_name = metadata['cluster_name']
                AlbaController._logger.info('Claimed {0} managed arakoon cluster: {1}'.format('externally' if storagerouter is None else 'internally', nsm_service_name))
                AlbaController.register_nsm(abm_service_name, nsm_service_name, clients.keys()[0])
                nsm_service = AlbaController._model_service(service_name=nsm_service_name,
                                                            service_type=nsm_service_type,
                                                            ports=ports,
                                                            storagerouter=storagerouter,
                                                            junction_type=NSMService,
                                                            backend=alba_backend,
                                                            number=0)
                current_services[alba_backend]['nsm'].append(nsm_service)

        # Cluster extension
        for alba_backend in alba_backends:
            abm_service_name = AlbaController.get_abm_service_name(backend=alba_backend.backend)
            metadata = ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=abm_service_name)
            if 0 < len(current_services[alba_backend]['abm']) < len(available_storagerouters) and metadata['internal'] is True:
                for storagerouter, partition in available_storagerouters.iteritems():
                    if storagerouter.ip in current_ips[alba_backend]['abm']:
                        continue

                    result = ArakoonInstaller.extend_cluster(master_ip=current_ips[alba_backend]['abm'][0],
                                                             new_ip=storagerouter.ip,
                                                             cluster_name=abm_service_name,
                                                             base_dir=partition.folder)
                    AlbaController.link_plugins(client=clients[storagerouter],
                                                data_dir=partition.folder,
                                                plugins=[AlbaController.ABM_PLUGIN],
                                                cluster_name=abm_service_name)
                    abm_service = AlbaController._model_service(service_name=abm_service_name,
                                                                service_type=abm_service_type,
                                                                ports=[result['client_port'], result['messaging_port']],
                                                                storagerouter=storagerouter,
                                                                junction_type=ABMService,
                                                                backend=alba_backend)
                    ArakoonInstaller.restart_cluster_add(cluster_name=abm_service_name,
                                                         current_ips=current_ips[alba_backend]['abm'],
                                                         new_ip=storagerouter.ip,
                                                         filesystem=False)
                    AlbaController._update_abm_client_config(abm_name=abm_service_name,
                                                             ip=storagerouter.ip)
                    current_ips[alba_backend]['abm'].append(storagerouter.ip)
                    current_services[alba_backend]['abm'].append(abm_service)

    @staticmethod
    @add_hooks('setup', 'demote')
    def on_demote(cluster_ip, master_ip, offline_node_ips=None):
        """
        A node is being demoted
        :param cluster_ip: IP of the cluster node to execute this on
        :type cluster_ip: str

        :param master_ip: IP of the master of the cluster
        :type master_ip: str

        :param offline_node_ips: IPs of nodes which are offline
        :type offline_node_ips: list

        :return: None
        """
        _ = master_ip
        if offline_node_ips is None:
            offline_node_ips = []
        alba_backends = AlbaBackendList.get_albabackends()
        for alba_backend in alba_backends:
            abm_service_name = AlbaController.get_abm_service_name(backend=alba_backend.backend)
            nsm_service_name = AlbaController.get_nsm_service_name(backend=alba_backend.backend)
            abm_metadata = ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=abm_service_name)
            nsm_metadata = ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=nsm_service_name)
            if abm_metadata['internal'] is True:
                # Remove the node from the ABM
                AlbaController._logger.info('Shrinking ABM for backend "{0}"'.format(alba_backend.backend.name))
                abm_storagerouter_ips = [abm_service.service.storagerouter.ip for abm_service in alba_backend.abm_services]
                abm_remaining_ips = list(set(abm_storagerouter_ips).difference(set(offline_node_ips)))
                if len(alba_backend.abm_services) == 0:
                    raise RuntimeError('No ABM services found for ALBA backend "{0}"'.format(alba_backend.backend.name))
                if len(abm_remaining_ips) == 0:
                    raise RuntimeError('No other available nodes found in the ABM cluster')

                if cluster_ip in abm_storagerouter_ips:
                    AlbaController._logger.info('* Shrink ABM cluster')
                    ArakoonInstaller.shrink_cluster(deleted_node_ip=cluster_ip,
                                                    remaining_node_ip=abm_remaining_ips[0],
                                                    cluster_name=abm_service_name,
                                                    offline_nodes=offline_node_ips)

                    AlbaController._logger.info('* Restarting ABM cluster')
                    ArakoonInstaller.restart_cluster_remove(abm_service_name, abm_remaining_ips, filesystem=False)
                    AlbaController._update_abm_client_config(abm_name=abm_service_name,
                                                             ip=abm_remaining_ips[0])

                    AlbaController._logger.info('* Remove old ABM node from model')
                    abm_service = [abms for abms in alba_backend.abm_services if abms.service.storagerouter.ip == cluster_ip][0]
                    service_abm_service = abm_service.service
                    abm_service.delete()
                    service_abm_service.delete()

            if nsm_metadata['internal'] is True:
                # Remove the node from the NSM
                AlbaController._logger.info('Shrinking NSM for backend "{0}"'.format(alba_backend.backend.name))
                nsm_service_map = dict((nsm_service.service.name, nsm_service.number) for nsm_service in alba_backend.nsm_services)
                for nsm_service_name, nsm_service_number in nsm_service_map.iteritems():
                    nsm_storagerouter_ips = [nsm_service.service.storagerouter.ip for nsm_service in alba_backend.nsm_services
                                             if nsm_service.service.is_internal is True and nsm_service.service.name == nsm_service_name]
                    nsm_remaining_ips = list(set(nsm_storagerouter_ips).difference(set(offline_node_ips)))
                    if len(nsm_remaining_ips) == 0:
                        raise RuntimeError('No other available nodes found in the NSM cluster')

                    if cluster_ip in nsm_storagerouter_ips:
                        AlbaController._logger.info('* Shrink NSM cluster {0}'.format(nsm_service_number))
                        ArakoonInstaller.shrink_cluster(deleted_node_ip=cluster_ip,
                                                        remaining_node_ip=nsm_remaining_ips[0],
                                                        cluster_name=nsm_service_name,
                                                        offline_nodes=offline_node_ips)

                        AlbaController._logger.info('* Restarting NSM cluster {0}'.format(nsm_service_number))
                        ArakoonInstaller.restart_cluster_remove(nsm_service_name, nsm_remaining_ips, filesystem=False)
                        AlbaController.update_nsm(abm_service_name, nsm_service_name, nsm_remaining_ips[0])

                        AlbaController._logger.info('* Remove old NSM node from model')
                        nsm_service = [nsm_service for nsm_service in alba_backend.nsm_services if nsm_service.service.name == nsm_service_name and nsm_service.service.storagerouter.ip == cluster_ip][0]
                        service_nsm_service = nsm_service.service
                        nsm_service.delete()
                        service_nsm_service.delete()

    @staticmethod
    @add_hooks('setup', 'remove')
    def on_remove(cluster_ip):
        """
        A node is removed
        :param cluster_ip: IP of the node being removed
        :type cluster_ip: str

        :return: None
        """
        for alba_backend in AlbaBackendList.get_albabackends():
            for nsm_service in alba_backend.nsm_services:
                service = nsm_service.service
                if service.is_internal is True and service.storagerouter.ip == cluster_ip:
                    nsm_service.delete()
                    service.delete()

        storage_router = StorageRouterList.get_by_ip(cluster_ip)
        from ovs.lib.albanodecontroller import AlbaNodeController
        for alba_node in storage_router.alba_nodes:
            for disk in alba_node.disks:
                for osd in disk.osds:
                    AlbaNodeController.remove_asd(node_guid=osd.alba_disk.alba_node_guid, asd_id=osd.osd_id, expected_safety=None)
                AlbaNodeController.remove_disk(node_guid=disk.alba_node_guid, disk=disk.name)
            alba_node.delete()
        for service in storage_router.services:
            if service.abm_service is not None:
                service.abm_service.delete()
            service.delete()

    @staticmethod
    @celery.task(name='alba.nsm_checkup', schedule=crontab(minute='45', hour='*'))
    @ensure_single(task_name='alba.nsm_checkup', mode='CHAINED')
    def nsm_checkup(allow_offline=False, backend_guid=None, min_nsms=None):
        """
        Validates the current NSM setup/configuration and takes actions where required.
        Assumptions:
        * A 2 node NSM is considered safer than a 1 node NSM.
        * When adding an NSM, the nodes with the least amount of NSM participation are preferred

        :param allow_offline: Ignore offline nodes
        :type allow_offline: bool

        :param backend_guid: Run for a specific backend
        :type backend_guid: str

        :param min_nsms: Minimum amount of NSM hosts that need to be provided
        :type min_nsms: int

        :return: None
        """
        alba_backends = AlbaBackendList.get_albabackends() if backend_guid is None else [AlbaBackend(backend_guid)]
        failed_backends = []
        for alba_backend in alba_backends:
            try:
                nsm_service_type = ServiceTypeList.get_by_name(ServiceType.SERVICE_TYPES.NS_MGR)
                safety = Configuration.get('/ovs/framework/plugins/alba/config|nsm.safety')
                maxload = Configuration.get('/ovs/framework/plugins/alba/config|nsm.maxload')

                abm_service_name = AlbaController.get_abm_service_name(backend=alba_backend.backend)
                nsm_service_name = AlbaController.get_nsm_service_name(backend=alba_backend.backend)
                nsm_metadata = ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=nsm_service_name)
                AlbaController._logger.debug('Ensuring NSM safety for backend {0}'.format(abm_service_name))
                nsm_groups = {}
                nsm_storagerouter = {}
                nsm_loads = {}
                for abm_service in alba_backend.abm_services:
                    if abm_service.service.is_internal is True:
                        storagerouter = abm_service.service.storagerouter
                        if storagerouter not in nsm_storagerouter:
                            nsm_storagerouter[storagerouter] = 0
                for nsm_service in alba_backend.nsm_services:
                    number = nsm_service.number
                    if number not in nsm_groups:
                        nsm_groups[number] = []
                        nsm_loads[number] = AlbaController.get_load(nsm_service)
                    nsm_groups[number].append(nsm_service)
                    if nsm_service.service.is_internal is True:
                        storagerouter = nsm_service.service.storagerouter
                        if storagerouter not in nsm_storagerouter:
                            nsm_storagerouter[storagerouter] = 0
                        nsm_storagerouter[storagerouter] += 1
                clients = {}
                for sr in nsm_storagerouter.keys():
                    try:
                        clients[sr] = SSHClient(sr)
                    except UnableToConnectException:
                        if allow_offline is True:
                            AlbaController._logger.debug('Storage Router with IP {0} is not reachable'.format(sr.ip))
                        else:
                            raise RuntimeError('Not all StorageRouters are reachable')

                # Safety
                if nsm_metadata['internal'] is True:
                    for number, nsm_services in nsm_groups.iteritems():
                        AlbaController._logger.debug('Processing NSM {0}'.format(number))
                        # Check amount of nodes
                        if len(nsm_services) < safety:
                            AlbaController._logger.debug('Insufficient nodes, extending if possible')
                            # Not enough nodes, let's see what can be done
                            current_srs = [nsm_service.service.storagerouter for nsm_service in nsm_services]
                            current_nsm = nsm_services[0]
                            available_srs = [storagerouter for storagerouter in nsm_storagerouter.keys() if storagerouter not in current_srs]
                            nsm_service_name = current_nsm.service.name
                            # As long as there are available StorageRouters and still not enough StorageRouters configured
                            while len(available_srs) > 0 and len(current_srs) < safety:
                                AlbaController._logger.debug('Adding node')
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
                                AlbaController._logger.debug('  Extending cluster config')
                                candidate_sr.invalidate_dynamics(['partition_config'])
                                partition = DiskPartition(candidate_sr.partition_config[DiskPartition.ROLES.DB][0])
                                nsm_result = ArakoonInstaller.extend_cluster(master_ip=current_nsm.service.storagerouter.ip,
                                                                             new_ip=candidate_sr.ip,
                                                                             cluster_name=nsm_service_name,
                                                                             base_dir=partition.folder)
                                AlbaController._logger.debug('  Linking plugin')
                                AlbaController.link_plugins(client=clients[candidate_sr],
                                                            data_dir=partition.folder,
                                                            plugins=[AlbaController.NSM_PLUGIN],
                                                            cluster_name=nsm_service_name)
                                AlbaController._logger.debug('  Model services')
                                AlbaController._model_service(service_name=nsm_service_name,
                                                              service_type=nsm_service_type,
                                                              ports=[nsm_result['client_port'], nsm_result['messaging_port']],
                                                              storagerouter=candidate_sr,
                                                              junction_type=NSMService,
                                                              backend=alba_backend,
                                                              number=current_nsm.number)
                                AlbaController._logger.debug('  Restart sequence')
                                ArakoonInstaller.restart_cluster_add(cluster_name=nsm_service_name,
                                                                     current_ips=[sr.ip for sr in current_srs],
                                                                     new_ip=candidate_sr.ip,
                                                                     filesystem=False)
                                AlbaController.update_nsm(abm_name=abm_service_name,
                                                          nsm_name=nsm_service_name,
                                                          ip=candidate_sr.ip)
                                AlbaController._logger.debug('Node added')

                # Load and minimum nsm hosts
                nsms_to_add = 0
                load_ok = min(nsm_loads.values()) < maxload
                AlbaController._logger.debug('Currently {0} NSM hosts'.format(len(nsm_loads)))
                if min_nsms is not None:
                    AlbaController._logger.debug('Minimum {0} NSM hosts requested'.format(min_nsms))
                    nsms_to_add = max(0, min_nsms - len(nsm_loads))
                if load_ok:
                    AlbaController._logger.debug('NSM load OK')
                else:
                    AlbaController._logger.debug('NSM load NOT OK')
                    nsms_to_add = max(1, nsms_to_add)
                if nsms_to_add > 0:
                    AlbaController._logger.debug('Trying to add {0} NSM hosts'.format(nsms_to_add))
                base_number = max(nsm_loads.keys()) + 1
                for number in xrange(base_number, base_number + nsms_to_add):
                    if nsm_metadata['internal'] is False:
                        AlbaController._logger.debug('Externally managed NSM arakoon cluster needs to be expanded')
                        metadata = ArakoonInstaller.get_unused_arakoon_metadata_and_claim(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM)
                        if metadata is None:
                            AlbaController._logger.warning('Cannot claim additional NSM clusters, because no clusters are available')
                            break
                        else:
                            client = None
                            masters = StorageRouterList.get_masters()
                            for master in masters:
                                try:
                                    client = SSHClient(master)
                                    break
                                except UnableToConnectException:
                                    continue
                            if client is None:
                                raise ValueError('Could not find an online master node')
                            AlbaController._model_service(service_name=metadata['cluster_name'],
                                                          service_type=nsm_service_type,
                                                          ports=[],
                                                          storagerouter=None,
                                                          junction_type=NSMService,
                                                          backend=alba_backend,
                                                          number=number)
                            AlbaController.register_nsm(abm_name=abm_service_name,
                                                        nsm_name=metadata['cluster_name'],
                                                        ip=client.ip)
                    else:
                        AlbaController._logger.debug('Adding new NSM')
                        # One of the NSM nodes is overloaded. This means the complete NSM is considered overloaded
                        # Figure out which StorageRouters are the least occupied
                        loads = sorted(nsm_storagerouter.values())[:safety]
                        nsm_name = '{0}-nsm_{1}'.format(alba_backend.name, number)
                        storagerouters = []
                        for storagerouter in nsm_storagerouter:
                            if nsm_storagerouter[storagerouter] in loads:
                                storagerouters.append(storagerouter)
                            if len(storagerouters) == safety:
                                break
                        # Creating a new NSM cluster
                        first_ip = None
                        metadata = None
                        for storagerouter in storagerouters:
                            nsm_storagerouter[storagerouter] += 1
                            storagerouter.invalidate_dynamics(['partition_config'])
                            partition = DiskPartition(storagerouter.partition_config[DiskPartition.ROLES.DB][0])
                            if first_ip is None:
                                nsm_result = ArakoonInstaller.create_cluster(cluster_name=nsm_name,
                                                                             cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM,
                                                                             ip=storagerouter.ip,
                                                                             base_dir=partition.folder,
                                                                             plugins=[AlbaController.NSM_PLUGIN])
                                first_ip = storagerouter.ip
                                metadata = nsm_result['metadata']
                            else:
                                nsm_result = ArakoonInstaller.extend_cluster(master_ip=first_ip,
                                                                             new_ip=storagerouter.ip,
                                                                             cluster_name=nsm_name,
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
                                                          backend=alba_backend,
                                                          number=number)
                        for storagerouter in storagerouters:
                            client = SSHClient(storagerouter, username='root')
                            ArakoonInstaller.start(nsm_name, client)
                        if metadata is not None:
                            ArakoonInstaller.claim_cluster(cluster_name=nsm_name,
                                                           master_ip=first_ip,
                                                           filesystem=False,
                                                           metadata=metadata)
                        AlbaController.register_nsm(abm_name=abm_service_name,
                                                    nsm_name=nsm_name,
                                                    ip=storagerouters[0].ip)
                        AlbaController._logger.debug('New NSM ({0}) added'.format(number))
            except Exception:
                AlbaController._logger.exception('NSM Checkup failed for backend {0}'.format(alba_backend.name))
                failed_backends.append(alba_backend.name)
        if len(failed_backends) > 0:
            raise RuntimeError('Checking NSM failed for ALBA backends: {0}'.format(', '.join(failed_backends)))

    @staticmethod
    @celery.task(name='alba.calculate_safety')
    def calculate_safety(alba_backend_guid, removal_osd_ids):
        """
        Calculates/loads the safety when a certain set of disks are removed
        :param alba_backend_guid: Guid of the ALBA backend
        :type alba_backend_guid: str

        :param removal_osd_ids: ASDs to take into account for safety calculation
        :type removal_osd_ids: list

        :return: Amount of good, critical and lost ASDs
        :rtype: dict
        """
        alba_backend = AlbaBackend(alba_backend_guid)
        error_disks = []
        for disks in alba_backend.local_stack.values():
            for disk in disks.values():
                for asd_id, asd in disk['asds'].iteritems():
                    if asd['status'] == 'error':
                        error_disks.append(asd_id)
        extra_parameters = ['--include-decommissioning-as-dead']
        for osd in alba_backend.osds:
            if osd.osd_id in removal_osd_ids or osd.osd_id in error_disks:
                extra_parameters.append('--long-id={0}'.format(osd.osd_id))
        config = Configuration.get_configuration_path('/ovs/arakoon/{0}/config'.format(AlbaController.get_abm_service_name(backend=alba_backend.backend)))
        safety_data = AlbaCLI.run(command='get-disk-safety', config=config, to_json=True, extra_params=extra_parameters)
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
        :param nsm_service: NSM service to retrieve the load for
        :type nsm_service: NSMService

        :return: Load of the NSM service
        :rtype: float
        """
        service_capacity = float(nsm_service.capacity)
        if service_capacity < 0:
            return 50
        if service_capacity == 0:
            return float('inf')
        config = Configuration.get_configuration_path(ArakoonInstaller.CONFIG_KEY.format(nsm_service.alba_backend.abm_services[0].service.name))
        hosts_data = AlbaCLI.run(command='list-nsm-hosts', config=config, to_json=True)
        host = [host for host in hosts_data if host['id'] == nsm_service.service.name][0]
        usage = host['namespaces_count']
        return round(usage / service_capacity * 100.0, 5)

    @staticmethod
    def register_nsm(abm_name, nsm_name, ip):
        """
        Register the NSM service to the cluster
        :param abm_name: Name of the ABM service
        :type abm_name: str

        :param nsm_name: Name of the NSM service
        :type nsm_name: str

        :param ip: IP of node in the cluster to register
        :type ip: str

        :return: None
        """
        nsm_config_file = Configuration.get_configuration_path(ArakoonInstaller.CONFIG_KEY.format(nsm_name))
        abm_config_file = Configuration.get_configuration_path(ArakoonInstaller.CONFIG_KEY.format(abm_name))
        if ArakoonInstaller.wait_for_cluster(nsm_name, ip, filesystem=False) and ArakoonInstaller.wait_for_cluster(abm_name, ip, filesystem=False):
            client = SSHClient(ip)
            AlbaCLI.run(command='add-nsm-host', config=abm_config_file, extra_params=[nsm_config_file], client=client)

    @staticmethod
    def update_nsm(abm_name, nsm_name, ip):
        """
        Update the NSM service
        :param abm_name: Name of the ABM service
        :type abm_name: str
        :param nsm_name: Name of the NSM service
        :type nsm_name: str
        :param ip: IP of node in the cluster to update
        :type ip: str
        :return: None
        """
        nsm_config_file = Configuration.get_configuration_path(ArakoonInstaller.CONFIG_KEY.format(nsm_name))
        abm_config_file = Configuration.get_configuration_path(ArakoonInstaller.CONFIG_KEY.format(abm_name))
        if ArakoonInstaller.wait_for_cluster(nsm_name, ip, filesystem=False) and ArakoonInstaller.wait_for_cluster(abm_name, ip, filesystem=False):
            client = SSHClient(ip)
            AlbaCLI.run(command='update-nsm-host', config=abm_config_file, extra_params=[nsm_config_file], client=client)

    @staticmethod
    def _update_abm_client_config(abm_name, ip):
        """
        Update the client configuration for the ABM cluster
        :param abm_name: Name of the ABM service
        :type abm_name: str

        :param ip: Any IP of a remaining node in the cluster with the correct configuration file available
        :type ip: str

        :return: None
        """
        abm_config_file = Configuration.get_configuration_path(ArakoonInstaller.CONFIG_KEY.format(abm_name))
        client = SSHClient(ip)
        # Try 8 times, 1st time immediately, 2nd time after 2 secs, 3rd time after 4 seconds, 4th time after 8 seconds
        # This will be up to 2 minutes
        # Reason for trying multiple times is because after a cluster has been shrunk or extended,
        # master might not be known, thus updating config might fail
        AlbaCLI.run(command='update-abm-client-config', config=abm_config_file, attempts=8, client=client)

    @staticmethod
    def _model_service(service_name, service_type, ports, storagerouter, junction_type, backend, number=None):
        """
        Adds service to the model
        """
        AlbaController._logger.info('Model service: {0}'.format(str(service_name)))
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
    @add_hooks('update', 'metadata')
    def get_metadata_sdm(client):
        """
        Retrieve information about the SDM packages
        :param client: SSHClient on which to retrieve the metadata
        :type client: SSHClient

        :return: List of dictionaries which contain services to restart,
                                                    packages to update,
                                                    information about potential downtime
                                                    information about unmet prerequisites
        :rtype: list
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
        :type client: SSHClient

        :return: List of dictionaries which contain services to restart,
                                                    packages to update,
                                                    information about potential downtime
                                                    information about unmet prerequisites
        :rtype: list
        """
        downtime = []
        alba_services = set()
        arakoon_cluster_services = set()
        for albabackend in AlbaBackendList.get_albabackends():
            alba_services.add('{0}_{1}'.format(AlbaController.ALBA_MAINTENANCE_SERVICE_PREFIX, albabackend.backend.name))
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
        :param client: SSHClient to 1 of the master nodes (On which the update is initiated)
        :type client: SSHClient

        :return: None
        """
        storagerouter_ips = [sr.ip for sr in StorageRouterList.get_storagerouters()]
        other_storagerouter_ips = [ip for ip in storagerouter_ips if ip != client.ip]

        nodes_to_upgrade = []
        all_nodes_to_upgrade = []
        for node in AlbaNodeList.get_albanodes():
            version_info = node.client.get_update_information()
            # Some odd information we get back here, but we don't change it because backwards compatibility
            # Pending updates: SDM  ASD
            #                   Y    Y    -> installed = 1.0, version = 1.1
            #                   Y    N    -> installed = 1.0, version = 1.1
            #                   N    Y    -> installed = 1.0, version = 1.0  (They are equal, but there's an ASD update pending)
            #                   N    N    -> installed = 1.0, version =      (No version? This means there's no update)
            pending = version_info['version']
            installed = version_info['installed']
            if pending != '':  # If there is any update (SDM or ASD)
                if pending.startswith('1.6.') and installed.startswith('1.5.'):
                    # 2.6 to 2.7 upgrade
                    if node.ip not in storagerouter_ips:
                        AlbaController._logger.warning('A non-hyperconverged node with pending upgrade from 2.6 (1.5) to 2.7 (1.6) was detected. No upgrade possible')
                        return
                all_nodes_to_upgrade.append(node)
                if node.ip not in other_storagerouter_ips:
                    nodes_to_upgrade.append(node)

        for node in nodes_to_upgrade:
            AlbaController._logger.info('{0}: Upgrading SDM'.format(node.ip))
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
                    AlbaController._logger.warning('Attempt {0} to update SDM failed, trying again'.format(counter))
                    if counter == max_counter:
                        AlbaController._logger.error('{0}: Error during update: {1}'.format(node.ip, ex.message))
                    time.sleep(10)
            if status != 'done':
                AlbaController._logger.error('{0}: Failed to perform SDM update. Please check /var/log/upstart/alba-asdmanager.log on the appropriate node'.format(node.ip))
                raise Exception('Status after upgrade is "{0}"'.format(status))
            node.client.restart_services()
            all_nodes_to_upgrade.remove(node)

        for alba_backend in AlbaBackendList.get_albabackends():
            service_name = '{0}_{1}'.format(AlbaController.ALBA_MAINTENANCE_SERVICE_PREFIX, alba_backend.backend.name)
            if ServiceManager.has_service(service_name, client=client) is True:
                if ServiceManager.get_service_status(service_name, client=client)[0] is True:
                    ServiceManager.stop_service(service_name, client=client)
                ServiceManager.remove_service(service_name, client=client)

        AlbaController.checkup_maintenance_agents.delay()

    @staticmethod
    @add_hooks('update', 'postupgrade')
    def restart_arakoon_clusters(client):
        """
        Restart all arakoon clusters after arakoon and/or alba package upgrade
        :param client: SSHClient to 1 of the master nodes (On which the update is initiated)
        :type client: SSHClient

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
            AlbaController._logger.info('Restarting cluster {0}'.format(cluster_name), print_msg=True)
            ArakoonInstaller.restart_cluster(cluster_name=cluster_name,
                                             master_ip=client.ip,
                                             filesystem=False)
        else:  # In case no arakoon clusters are restarted, we check if alba has been updated and still restart clusters
            proxies = []
            this_sr = StorageRouterList.get_by_ip(client.ip)
            for sr in StorageRouterList.get_storagerouters():
                for service in sr.services:
                    if service.type.name == ServiceType.SERVICE_TYPES.ALBA_PROXY and service.storagerouter_guid == this_sr.guid:
                        proxies.append(service.name)
            if proxies:
                info = PackageManager.verify_update_required(packages=['alba'],
                                                             services=proxies,
                                                             client=client)
                if info['services']:
                    for service in services:
                        cluster_name = service.lstrip('arakoon-')
                        AlbaController._logger.info('Restarting cluster {0} because of ALBA update'.format(cluster_name), print_msg=True)
                        ArakoonInstaller.restart_cluster(cluster_name=cluster_name,
                                                         master_ip=client.ip,
                                                         filesystem=False)

    @staticmethod
    @add_hooks('setup', ['firstnode', 'extranode'])  # Arguments: cluster_ip and for extranode also master_ip
    @add_hooks('plugin', ['postinstall'])  # Arguments: ip
    def _add_base_configuration(*args, **kwargs):
        _ = args, kwargs
        key = '/ovs/framework/plugins/alba/config'
        if not Configuration.exists(key):
            Configuration.set(key, {'nsm': {'maxload': 75,
                                            'safety': 3}})
        key = '/ovs/framework/plugins/installed'
        installed = Configuration.get(key)
        if 'alba' not in installed['backends']:
            installed['backends'].append('alba')
            Configuration.set(key, installed)
        key = '/ovs/alba/backends/global_gui_error_interval'
        if not Configuration.exists(key):
            Configuration.set(key, 300)
        key = '/ovs/framework/hosts/{0}/versions|alba'
        for storagerouter in StorageRouterList.get_storagerouters():
            machine_id = storagerouter.machine_id
            if not Configuration.exists(key.format(machine_id)):
                Configuration.set(key.format(machine_id), 9)

    @staticmethod
    @add_hooks('update', 'postupgrade')
    def upgrade_alba_plugin(client):
        """
        Upgrade the ALBA plugin
        :param client: SSHClient to connect to for upgrade
        :type client: SSHClient

        :return: None
        """
        from ovs.dal.lists.albabackendlist import AlbaBackendList
        alba_backends = AlbaBackendList.get_albabackends()
        for alba_backend in alba_backends:
            alba_backend_name = alba_backend.backend.name
            service_name = '{0}_{1}'.format(AlbaController.ALBA_REBALANCER_SERVICE_PREFIX, alba_backend_name)
            if ServiceManager.has_service(service_name, client=client) is True:
                if ServiceManager.get_service_status(service_name, client=client)[0] is True:
                    ServiceManager.stop_service(service_name, client=client)
                ServiceManager.remove_service(service_name, client=client)

    @staticmethod
    @celery.task(name='alba.link_alba_backends')
    def link_alba_backends(alba_backend_guid, metadata):
        """
        Link a GLOBAL ALBA Backend to a LOCAL or another GLOBAL ALBA Backend
        :param alba_backend_guid: ALBA backend guid to link another ALBA Backend to
        :type alba_backend_guid: str

        :param metadata: Metadata about the linked ALBA Backend
        :type metadata: dict
        """
        Toolbox.verify_required_params(required_params={'backend_connection_info': (dict, {'host': (str, Toolbox.regex_ip),
                                                                                           'port': (int, {'min': 1, 'max': 65535}),
                                                                                           'username': (str, None),
                                                                                           'password': (str, None)}),
                                                        'backend_info': (dict, {'linked_guid': (str, Toolbox.regex_guid),
                                                                                'linked_name': (str, Toolbox.regex_vpool),
                                                                                'linked_preset': (str, Toolbox.regex_preset),
                                                                                'linked_alba_id': (str, Toolbox.regex_guid)})},
                                       actual_params=metadata)

        # Verify OSD has already been added
        added = False
        claimed = False
        config = Configuration.get_configuration_path('/ovs/arakoon/{0}/config'.format(AlbaController.get_abm_service_name(backend=AlbaBackend(alba_backend_guid).backend)))
        all_osds = AlbaCLI.run(command='list-all-osds', config=config, to_json=True)
        linked_alba_id = metadata['backend_info']['linked_alba_id']
        for osd in all_osds:
            if osd.get('long_id') == linked_alba_id:
                added = True
                claimed = osd.get('alba_id') is not None
                break

        # Add the OSD
        if added is False:
            # Retrieve remote arakoon configuration
            connection_info = metadata['backend_connection_info']
            ovs_client = OVSClient(ip=connection_info['host'], port=connection_info['port'], credentials=(connection_info['username'], connection_info['password']))
            task_id = ovs_client.get('/alba/backends/{0}/get_config_metadata'.format(metadata['backend_info']['linked_guid']))
            successful, arakoon_config = ovs_client.wait_for_task(task_id, timeout=300)
            if successful is False:
                raise RuntimeError('Could not load metadata from environment {0}'.format(ovs_client.ip))

            # Write arakoon configuration to file
            raw_config = RawConfigParser()
            for section in arakoon_config:
                raw_config.add_section(section)
                for key, value in arakoon_config[section].iteritems():
                    raw_config.set(section, key, value)
            config_io = StringIO()
            raw_config.write(config_io)
            remote_arakoon_config = '/opt/OpenvStorage/arakoon_config_temp'
            with open(remote_arakoon_config, 'w') as arakoon_cfg:
                arakoon_cfg.write(config_io.getvalue())

            try:
                AlbaCLI.run(command='add-osd',
                            config=config,
                            prefix=alba_backend_guid,
                            preset=metadata['backend_info']['linked_preset'],
                            node_id=metadata['backend_info']['linked_guid'],
                            to_json=True,
                            alba_osd_config_url='file://{0}'.format(remote_arakoon_config))
            finally:
                os.remove(remote_arakoon_config)

        if claimed is False:
            # Claim and update model
            AlbaController.add_units(alba_backend_guid=alba_backend_guid, osds={linked_alba_id: None}, metadata=metadata)

    @staticmethod
    @celery.task(name='alba.unlink_alba_backends')
    def unlink_alba_backends(target_guid, linked_guid):
        """
        Unlink a LOCAL or GLOBAL ALBA Backend from a GLOBAL ALBA Backend
        :param target_guid: Guid of the GLOBAL ALBA Backend from which a link will be removed
        :type target_guid: str

        :param linked_guid: Guid of the GLOBAL or LOCAL ALBA Backend which will be unlinked (Can be a local or a remote ALBA Backend)
        :type linked_guid: str
        """
        child = AlbaBackend(linked_guid)
        parent = AlbaBackend(target_guid)
        linked_osd = None
        for osd in parent.osds:
            if osd.metadata is not None and osd.metadata['backend_info']['linked_guid'] == child.guid:
                linked_osd = osd
                break

        if linked_osd is not None:
            AlbaController.remove_units(alba_backend_guid=parent.guid, osd_ids=[linked_osd.osd_id])
            linked_osd.delete()
        parent.invalidate_dynamics()
        parent.backend.invalidate_dynamics()

    @staticmethod
    @celery.task(name='alba.checkup_maintenance_agents', schedule=crontab(minute='0', hour='*'))
    @ensure_single(task_name='alba.checkup_maintenance_agents', mode='CHAINED')
    def checkup_maintenance_agents():
        """
        Check if requested nr of maintenance agents / backend is actually present
        Add / remove as necessary
        :return: None
        """
        service_template_key = 'alba-maintenance_{0}-{1}'

        def _generate_name(_backend_name):
            unique_hash = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(16))
            return service_template_key.format(_backend_name, unique_hash)

        def _count(_service_map):
            amount = 0
            for _services in _service_map.values():
                amount += len(_services)
            return amount

        def _add_service(_node, _service_name, _abackend):
            _name = _abackend.name
            try:
                _node.client.add_maintenance_service(name=_service_name,
                                                     alba_backend_guid=_abackend.guid,
                                                     abm_name=AlbaController.get_abm_service_name(_abackend.backend))
                return True
            except Exception:
                AlbaController._logger.exception('Could not add maintenance service for {0} on {1}'.format(_name, _node.ip))
            return False

        def _remove_service(_node, _service_name, _abackend):
            _name = _abackend.name
            try:
                _node.client.remove_maintenance_service(name=_service_name)
                return True
            except Exception:
                AlbaController._logger.exception('Could not remove maintenance service for {0} on {1}'.format(_name, _node.ip))
            return False

        AlbaController._logger.info('Loading maintenance information')
        service_map = {}
        node_load = {}
        available_node_map = {}
        all_nodes = []
        for node in AlbaNodeList.get_albanodes():
            try:
                service_names = node.client.list_maintenance_services()
            except Exception:
                AlbaController._logger.exception('* Cannot fetch maintenance information for {0}'.format(node.ip))
                continue

            for disk in node.disks:
                for osd in disk.osds:
                    backend_guid = osd.alba_backend_guid
                    if backend_guid not in available_node_map:
                        available_node_map[backend_guid] = set()
                    available_node_map[backend_guid].add(node)

            for service_name in service_names:
                backend_name, service_hash = service_name.split('_', 1)[1].rsplit('-', 1)  # E.g. alba-maintenance_mybackend-a4f7e3c61
                AlbaController._logger.debug('* Maintenance {0} for {1} on {2}'.format(service_hash, backend_name, node.ip))

                if backend_name not in service_map:
                    service_map[backend_name] = {}
                if node not in service_map[backend_name]:
                    service_map[backend_name][node] = []
                service_map[backend_name][node].append(service_name)

                if node not in node_load:
                    node_load[node] = 0
                node_load[node] += 1
            all_nodes.append(node)

        for alba_backend in AlbaBackendList.get_albabackends():
            name = alba_backend.name
            AlbaController._logger.info('Generating service worklog for {0}'.format(name))
            key = AlbaController.NR_OF_AGENTS_CONFIG_KEY.format(alba_backend.guid)
            if Configuration.exists(key):
                required_nr = Configuration.get(key)
            else:
                required_nr = 3
                Configuration.set(key, required_nr)
            if name not in service_map:
                service_map[name] = {}
            if alba_backend.guid not in available_node_map:
                available_node_map[alba_backend.guid] = []
            else:
                available_node_map[alba_backend.guid] = sorted(available_node_map[alba_backend.guid],
                                                               key=lambda n: node_load.get(n, 0))

            to_remove = {}
            to_add = {}
            # Clean out services on non-available nodes
            for node in service_map[name]:
                if node not in available_node_map[alba_backend.guid]:
                    if node not in to_remove:
                        to_remove[node] = []
                    service_names = service_map[name][node]
                    to_remove[node] += service_names
                    service_map[name][node] = []
                    AlbaController._logger.debug('* Candidates for removal (unused node): {0} on {1}'.format(service_names, node.ip))
            # Multiple services on a single node must be cleaned
            for node, service_names in service_map[name].iteritems():
                if len(service_names) > 1:
                    if node not in to_remove:
                        to_remove[node] = []
                    service_names = service_names[1:]
                    to_remove[node] += service_names
                    service_map[name][node] = service_names[0]
                    AlbaController._logger.debug('* Candidates for removal (too many services on node): {0} on {1}'.format(service_names, node.ip))
            # Add services if required
            if _count(service_map[name]) < required_nr:
                for node in available_node_map[alba_backend.guid]:
                    if node not in service_map[name]:
                        if node not in to_add:
                            service_name = _generate_name(name)
                            to_add[node] = service_name
                            service_map[name][node] = [service_name]
                            AlbaController._logger.debug('* Candidate add (not enough services): {0} on {1}'.format(service_name, node.ip))
                    if _count(service_map[name]) == required_nr:
                        break
            # Remove services if required
            if _count(service_map[name]) > required_nr:
                for node in reversed(available_node_map[alba_backend.guid]):
                    if node in service_map[name]:
                        if node not in to_remove:
                            to_remove[node] = []
                        for service_name in service_map[name][node][:]:
                            to_remove[node].append(service_name)
                            service_map[name][node].remove(service_name)
                            AlbaController._logger.debug('* Candidate removal (too many services): {0} on {1}'.format(service_name, node.ip))
                    if _count(service_map[name]) == required_nr:
                        break
            minimum = 1 if alba_backend.scaling == AlbaBackend.SCALINGS.LOCAL else 3
            # Make sure there's still at least one service left
            if _count(service_map[name]) == 0:
                for node in to_remove:
                    if len(to_remove[node]) > 0:
                        service_name = to_remove[node].pop()
                        AlbaController._logger.debug('* Removing removal candidate (at least {0} service required): {1} on {2}'.format(minimum, service_name, node.ip))
                        if node not in service_map[name]:
                            service_map[name][node] = []
                        service_map[name][node].append(service_name)
                    if _count(service_map[name]) == minimum:
                        break
                if _count(service_map[name]) < minimum and len(all_nodes) > 0:
                    for node in all_nodes:
                        if node not in to_add and node not in service_map[name]:
                            service_name = _generate_name(name)
                            to_add[node] = service_name
                            AlbaController._logger.debug('* Candidate add (at least {0} service required): {1} on {2}'.format(minimum, service_name, node.ip))
                            service_map[name][node] = [service_name]
                        if _count(service_map[name]) == minimum:
                            break

            AlbaController._logger.info('Applying service worklog for {0}'.format(name))
            for node, services in to_remove.iteritems():
                for service_name in services:
                    if _remove_service(node, service_name, alba_backend):
                        AlbaController._logger.info('* Removed service {0} on {1}: OK'.format(service_name, node.ip))
                    else:
                        AlbaController._logger.warning('* Removed service {0} on {1}: FAIL'.format(service_name, node.ip))
            for node, service_name in to_add.iteritems():
                if _add_service(node, service_name, alba_backend):
                    AlbaController._logger.info('* Added service {0} on {1}: OK'.format(service_name, node.ip))
                else:
                    AlbaController._logger.warning('* Added service {0} on {1}: FAIL'.format(service_name, node.ip))

            AlbaController._logger.info('Finished service worklog for {0}'.format(name))


if __name__ == '__main__':
    try:
        while True:
            _output = ['',
                       'Open vStorage - NSM/ABM debug information',
                       '=========================================',
                       'timestamp: {0}'.format(time.time()),
                       '']
            _alba_backends = AlbaBackendList.get_albabackends()
            for _sr in StorageRouterList.get_storagerouters():
                _output.append('+ {0} ({1})'.format(_sr.name, _sr.ip))
                for _alba_backend in _alba_backends:
                    _output.append('  + {0}'.format(_alba_backend.backend.name))
                    for _abm_service in _alba_backend.abm_services:
                        if _abm_service.service.is_internal is False:
                            _output.append('    + ABM (externally managed)')
                        elif _abm_service.service.storagerouter_guid == _sr.guid:
                            _output.append('    + ABM - port {0}'.format(_abm_service.service.ports))
                    for _nsm_service in _alba_backend.nsm_services:
                        internal = _nsm_service.service.is_internal
                        if _nsm_service.service.storagerouter_guid == _sr.guid or internal is False:
                            _service_capacity = 'infinite' if float(_nsm_service.capacity) < 0 else float(_nsm_service.capacity)
                            _load = AlbaController.get_load(_nsm_service)
                            _load = 'infinite' if _load == float('inf') else '{0}%'.format(round(_load, 2))

                            if internal is True:
                                _output.append('    + NSM {0} - port {1} - capacity: {2}, load: {3}'.format(_nsm_service.number,
                                                                                                            _nsm_service.service.ports,
                                                                                                            _service_capacity,
                                                                                                            _load))
                            else:
                                _output.append('    + NSM {0} (externally managed) - capacity: {1}, load: {2}'.format(_nsm_service.number,
                                                                                                                      _service_capacity,
                                                                                                                      _load))
            _output += ['',
                        'Press ^C to exit',
                        '']
            print '\x1b[2J\x1b[H' + '\n'.join(_output)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
