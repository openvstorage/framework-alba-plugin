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
import re
import time
import string
import random
import datetime
import requests
from ovs.dal.exceptions import ObjectNotFoundException
from ovs.dal.hybrids.albaabmcluster import ABMCluster
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.albadisk import AlbaDisk
from ovs.dal.hybrids.albansmcluster import NSMCluster
from ovs.dal.hybrids.albaosd import AlbaOSD
from ovs.dal.hybrids.backend import Backend
from ovs.dal.hybrids.diskpartition import DiskPartition
from ovs.dal.hybrids.domain import Domain
from ovs.dal.hybrids.j_abmservice import ABMService
from ovs.dal.hybrids.j_nsmservice import NSMService
from ovs.dal.hybrids.service import Service as DalService
from ovs.dal.hybrids.servicetype import ServiceType
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.servicetypelist import ServiceTypeList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs_extensions.api.client import OVSClient
from ovs.extensions.db.arakooninstaller import ArakoonClusterConfig, ArakoonInstaller
from ovs.extensions.generic.configuration import Configuration, NotFoundException
from ovs.extensions.generic.sshclient import SSHClient, UnableToConnectException
from ovs.extensions.plugins.albacli import AlbaCLI
from ovs.extensions.storage.volatilefactory import VolatileFactory
from ovs.lib.helpers.decorators import add_hooks, ovs_task
from ovs.lib.helpers.toolbox import Schedule, Toolbox
from ovs.log.log_handler import LogHandler


class AlbaController(object):
    """
    Contains all BLL related to ALBA
    """
    ABM_PLUGIN = 'albamgr_plugin'
    NSM_PLUGIN = 'nsm_host_plugin'
    ALBA_VERSION_GET = 'alba=`alba version --terse`'

    ARAKOON_PLUGIN_DIR = '/usr/lib/alba'
    CONFIG_ALBA_BACKEND_KEY = '/ovs/alba/backends/{0}'
    NR_OF_AGENTS_CONFIG_KEY = '/ovs/alba/backends/{0}/maintenance/nr_of_agents'
    AGENTS_LAYOUT_CONFIG_KEY = '/ovs/alba/backends/{0}/maintenance/agents_layout'
    CONFIG_DEFAULT_NSM_HOSTS_KEY = CONFIG_ALBA_BACKEND_KEY.format('default_nsm_hosts')

    _logger = LogHandler.get('lib', name='alba')

    @staticmethod
    @ovs_task(name='alba.add_units')
    def add_units(alba_backend_guid, osds, metadata=None):
        """
        Adds storage units to an Alba Backend
        :param alba_backend_guid: Guid of the ALBA Backend
        :type alba_backend_guid: str
        :param osds: ASDs to add to the ALBA Backend
        :type osds: dict
        :param metadata: Metadata to add to the OSD (connection information for remote Backend, general Backend information)
        :type metadata: dict
        :return: The OSD IDs that could not be claimed because they had already been claimed by another ALBA Backend
        :rtype: list
        """
        from ovs.extensions.plugins.albacli import AlbaError

        alba_backend = AlbaBackend(alba_backend_guid)
        if alba_backend.abm_cluster is None:
            raise ValueError('ALBA Backend {0} does not have an ABM cluster registered'.format(alba_backend.name))

        domain = None
        domain_guid = metadata['backend_info'].get('domain_guid') if metadata is not None else None
        if domain_guid is not None:
            try:
                domain = Domain(domain_guid)
            except ObjectNotFoundException:
                AlbaController._logger.warning('Provided Domain with guid {0} has been deleted in the meantime'.format(domain_guid))

        config = Configuration.get_configuration_path(key=alba_backend.abm_cluster.config_location)
        disks = {}

        service_deployed = False
        for alba_node in AlbaNodeList.get_albanodes():
            try:
                for service_name in alba_node.client.list_maintenance_services():
                    if re.match('^alba-maintenance_{0}-[a-zA-Z0-9]{{16}}$'.format(alba_backend.name), service_name):
                        service_deployed = True
                        break
            except:
                pass
            if service_deployed is True:
                break
        if service_deployed is False:
            raise Exception('No maintenance agents have been deployed for ALBA Backend {0}'.format(alba_backend.name))

        unclaimed_osds = []
        for osd_id, disk_guid in osds.iteritems():
            if disk_guid is not None and disk_guid not in disks:
                disks[disk_guid] = AlbaDisk(disk_guid)
            alba_disk = disks.get(disk_guid)
            try:
                AlbaCLI.run(command='claim-osd', config=config, named_params={'long-id': osd_id})
            except AlbaError as ae:
                if ae.error_code == 11:
                    AlbaController._logger.warning('OSD with ID {0} for disk {1} has already been claimed'.format(osd_id, disk_guid))
                    unclaimed_osds.append(osd_id)
                    continue
            osd = AlbaOSD()
            osd.domain = domain
            osd.osd_id = osd_id
            osd.osd_type = AlbaOSD.OSD_TYPES.ALBA_BACKEND if alba_disk is None else AlbaOSD.OSD_TYPES.ASD
            osd.metadata = metadata
            osd.alba_disk = alba_disk
            osd.alba_backend = alba_backend
            osd.save()
        alba_backend.invalidate_dynamics()
        alba_backend.backend.invalidate_dynamics()
        return unclaimed_osds

    @staticmethod
    @ovs_task(name='alba.remove_units')
    def remove_units(alba_backend_guid, osd_ids):
        """
        Removes storage units from an Alba Backend
        :param alba_backend_guid: Guid of the ALBA Backend
        :type alba_backend_guid: str
        :param osd_ids: IDs of the ASDs
        :type osd_ids: list
        :return: None
        """
        alba_backend = AlbaBackend(alba_backend_guid)
        if alba_backend.abm_cluster is None:
            raise ValueError('ALBA Backend {0} does not have an ABM cluster registered'.format(alba_backend.name))

        config = Configuration.get_configuration_path(key=alba_backend.abm_cluster.config_location)
        failed_osds = []
        last_exception = None
        for osd_id in osd_ids:
            try:
                AlbaCLI.run(command='purge-osd', config=config, named_params={'long-id': osd_id})
            except Exception as ex:
                if 'Albamgr_protocol.Protocol.Error.Osd_unknown' not in ex.message:
                    AlbaController._logger.exception('Error purging OSD {0}'.format(osd_id))
                    last_exception = ex
                    failed_osds.append(osd_id)
        if len(failed_osds) > 0:
            if len(osd_ids) == 1:
                raise last_exception
            raise RuntimeError('Error processing one or more OSDs: {0}'.format(failed_osds))

    @staticmethod
    @ovs_task(name='alba.add_cluster')
    def add_cluster(alba_backend_guid, abm_cluster=None, nsm_clusters=None):
        """
        Adds an Arakoon cluster to service Backend
        :param alba_backend_guid: Guid of the ALBA Backend
        :type alba_backend_guid: str
        :param abm_cluster: ABM cluster to use for this ALBA Backend
        :type abm_cluster: str
        :param nsm_clusters: NSM clusters to use for this ALBA Backend
        :type nsm_clusters: list[str]
        :return: None
        :rtype: NoneType
        """
        from ovs.lib.albanode import AlbaNodeController
        alba_backend = AlbaBackend(alba_backend_guid)

        if nsm_clusters is None:
            nsm_clusters = []
        try:
            counter = 0
            while counter < 300:
                if AlbaController.manual_alba_arakoon_checkup(alba_backend_guid=alba_backend_guid,
                                                              abm_cluster=abm_cluster,
                                                              nsm_clusters=nsm_clusters) is True:
                    break
                counter += 1
                time.sleep(1)
                if counter == 300:
                    raise RuntimeError('Arakoon checkup for ALBA Backend {0} could not be started'.format(alba_backend.name))
        except Exception as ex:
            AlbaController._logger.exception('Failed manual Alba Arakoon checkup during add cluster for Backend {0}. {1}'.format(alba_backend_guid, ex))
            AlbaController.remove_cluster(alba_backend_guid=alba_backend_guid)
            raise

        config = Configuration.get_configuration_path(key=alba_backend.abm_cluster.config_location)
        alba_backend.alba_id = AlbaCLI.run(command='get-alba-id', config=config, named_params={'attempts': 5})['id']
        alba_backend.save()
        if not Configuration.exists(AlbaController.CONFIG_DEFAULT_NSM_HOSTS_KEY):
            Configuration.set(AlbaController.CONFIG_DEFAULT_NSM_HOSTS_KEY, 1)
        nsms = max(1, Configuration.get(AlbaController.CONFIG_DEFAULT_NSM_HOSTS_KEY))
        try:
            AlbaController.nsm_checkup(alba_backend_guid=alba_backend.guid, min_nsms=nsms)
        except Exception as ex:
            AlbaController._logger.exception('Failed NSM checkup during add cluster for Backend {0}. {1}'.format(alba_backend.guid, ex))
            AlbaController.remove_cluster(alba_backend_guid=alba_backend.guid)
            raise

        # Enable LRU
        key = AlbaController.CONFIG_ALBA_BACKEND_KEY.format('lru_redis')
        if Configuration.exists(key, raw=True):
            endpoint = Configuration.get(key, raw=True).strip().strip('/')
        else:
            masters = StorageRouterList.get_masters()
            endpoint = 'redis://{0}:6379'.format(masters[0].ip)
        redis_endpoint = '{0}/alba_lru_{1}'.format(endpoint, alba_backend.guid)
        AlbaCLI.run(command='update-maintenance-config', config=config, named_params={'set-lru-cache-eviction': redis_endpoint})

        # Mark the Backend as 'running'
        alba_backend.backend.status = 'RUNNING'
        alba_backend.backend.save()

        AlbaNodeController.model_albanodes()
        AlbaController.checkup_maintenance_agents.delay()
        alba_backend.invalidate_dynamics('live_status')

    @staticmethod
    @ovs_task(name='alba.remove_cluster')
    def remove_cluster(alba_backend_guid):
        """
        Removes an Alba Backend/cluster
        :param alba_backend_guid: Guid of the ALBA Backend
        :type alba_backend_guid: str
        :return: None
        """
        # VALIDATIONS
        alba_backend = AlbaBackend(alba_backend_guid)
        if len(alba_backend.osds) > 0:
            raise RuntimeError('An ALBA Backend with claimed OSDs cannot be removed')

        if alba_backend.abm_cluster is not None:
            # Check ABM cluster reachable
            for abm_service in alba_backend.abm_cluster.abm_services:
                if abm_service.service.is_internal is True:
                    service = abm_service.service
                    try:
                        SSHClient(endpoint=service.storagerouter, username='root')
                    except UnableToConnectException:
                        raise RuntimeError('Node {0} with IP {1} is not reachable, ALBA Backend cannot be removed.'.format(service.storagerouter.name, service.storagerouter.ip))

            # Check all NSM clusters reachable
            for nsm_cluster in alba_backend.nsm_clusters:
                for nsm_service in nsm_cluster.nsm_services:
                    service = nsm_service.service
                    if service.is_internal is True:
                        try:
                            SSHClient(endpoint=service.storagerouter, username='root')
                        except UnableToConnectException:
                            raise RuntimeError('Node {0} with IP {1} is not reachable, ALBA Backend cannot be removed'.format(service.storagerouter.name, service.storagerouter.ip))

        # Check storage nodes reachable
        for alba_node in AlbaNodeList.get_albanodes():
            try:
                alba_node.client.list_maintenance_services()
            except requests.exceptions.ConnectionError as ce:
                raise RuntimeError('Node {0} is not reachable, ALBA Backend cannot be removed. {1}'.format(alba_node.ip, ce))

        # ACTUAL REMOVAL
        if alba_backend.abm_cluster is not None:
            AlbaController._logger.debug('Removing ALBA Backend {0}'.format(alba_backend.name))
            internal = alba_backend.abm_cluster.abm_services[0].service.is_internal
            abm_cluster_name = alba_backend.abm_cluster.name
            arakoon_clusters = list(Configuration.list('/ovs/arakoon'))
            if abm_cluster_name in arakoon_clusters:
                # Remove ABM Arakoon cluster
                arakoon_installer = ArakoonInstaller(cluster_name=abm_cluster_name)
                if internal is True:
                    AlbaController._logger.debug('Deleting ALBA manager Arakoon cluster {0}'.format(abm_cluster_name))
                    arakoon_installer.delete_cluster()
                    AlbaController._logger.debug('Deleted ALBA manager Arakoon cluster {0}'.format(abm_cluster_name))
                else:
                    AlbaController._logger.debug('Un-claiming ALBA manager Arakoon cluster {0}'.format(abm_cluster_name))
                    arakoon_installer.unclaim_cluster()
                    AlbaController._logger.debug('Unclaimed ALBA manager Arakoon cluster {0}'.format(abm_cluster_name))

            # Remove ABM Arakoon services
            for abm_service in alba_backend.abm_cluster.abm_services:
                abm_service.delete()
                abm_service.service.delete()
                if internal is True:
                    AlbaController._logger.debug('Removed service {0} on node {1}'.format(abm_service.service.name, abm_service.service.storagerouter.name))
                else:
                    AlbaController._logger.debug('Removed service {0}'.format(abm_service.service.name))
            alba_backend.abm_cluster.delete()

            # Remove NSM Arakoon clusters and services
            for nsm_cluster in alba_backend.nsm_clusters:
                if nsm_cluster.name in arakoon_clusters:
                    arakoon_installer = ArakoonInstaller(cluster_name=nsm_cluster.name)
                    if internal is True:
                        AlbaController._logger.debug('Deleting Namespace manager Arakoon cluster {0}'.format(nsm_cluster.name))
                        arakoon_installer.delete_cluster()
                        AlbaController._logger.debug('Deleted Namespace manager Arakoon cluster {0}'.format(nsm_cluster.name))
                    else:
                        AlbaController._logger.debug('Un-claiming Namespace manager Arakoon cluster {0}'.format(nsm_cluster.name))
                        arakoon_installer.unclaim_cluster()
                        AlbaController._logger.debug('Unclaimed Namespace manager Arakoon cluster {0}'.format(nsm_cluster.name))
                for nsm_service in nsm_cluster.nsm_services:
                    nsm_service.delete()
                    nsm_service.service.delete()
                    AlbaController._logger.debug('Removed service {0}'.format(nsm_service.service.name))
                nsm_cluster.delete()

        # Delete maintenance agents
        for node in AlbaNodeList.get_albanodes():
            try:
                for service_name in node.client.list_maintenance_services():
                    backend_name = service_name.split('_', 1)[1].rsplit('-', 1)[0]  # E.g. alba-maintenance_my-backend-a4f7e3c61
                    if backend_name == alba_backend.name:
                        node.client.remove_maintenance_service(service_name)
                        AlbaController._logger.info('Removed maintenance service {0} on {1}'.format(service_name, node.ip))
            except Exception:
                AlbaController._logger.exception('Could not clean up maintenance services for {0}'.format(alba_backend.name))

        config_key = AlbaController.CONFIG_ALBA_BACKEND_KEY.format(alba_backend_guid)
        AlbaController._logger.debug('Deleting ALBA Backend entry {0} from configuration management'.format(config_key))
        Configuration.delete(config_key)

        AlbaController._logger.debug('Deleting ALBA Backend from model')
        backend = alba_backend.backend
        for junction in list(backend.domains):
            junction.delete()
        alba_backend.delete()
        backend.delete()

    @staticmethod
    @ovs_task(name='alba.get_arakoon_config')
    def get_arakoon_config(alba_backend_guid):
        """
        Gets the Arakoon configuration for an Alba Backend
        :param alba_backend_guid: Guid of the ALBA Backend
        :type alba_backend_guid: str
        :return: Arakoon cluster configuration information
        :rtype: dict
        """
        alba_backend = AlbaBackend(alba_backend_guid)
        if alba_backend.abm_cluster is None:
            raise ValueError('ALBA Backend {0} does not have an ABM cluster registered'.format(alba_backend.name))

        client = None
        service = None
        for abm_service in alba_backend.abm_cluster.abm_services:
            service = abm_service.service
            if service.is_internal is True:
                try:
                    client = SSHClient(service.storagerouter.ip)
                    break
                except UnableToConnectException:
                    pass
        if service is None or (client is None and service.is_internal is True):
            raise RuntimeError('Could not load Arakoon configuration')

        config = ArakoonClusterConfig(cluster_id=alba_backend.abm_cluster.name)
        return config.export_dict()

    @staticmethod
    @ovs_task(name='alba.scheduled_alba_arakoon_checkup',
              schedule=Schedule(minute='30', hour='*'),
              ensure_single_info={'mode': 'DEFAULT', 'extra_task_names': ['alba.manual_alba_arakoon_checkup']})
    def scheduled_alba_arakoon_checkup():
        """
        Makes sure the volumedriver Arakoon is on all available master nodes
        :return: None
        """
        AlbaController._alba_arakoon_checkup()

    @staticmethod
    @ovs_task(name='alba.manual_alba_arakoon_checkup',
              ensure_single_info={'mode': 'DEFAULT', 'extra_task_names': ['alba.scheduled_alba_arakoon_checkup']})
    def manual_alba_arakoon_checkup(alba_backend_guid, nsm_clusters, abm_cluster=None):
        """
        Creates a new Arakoon cluster if required and extends cluster if possible on all available master nodes
        :param alba_backend_guid: Guid of the ALBA Backend
        :type alba_backend_guid: str
        :param nsm_clusters: NSM clusters for this ALBA Backend
        :type nsm_clusters: list[str]
        :param abm_cluster: ABM cluster for this ALBA Backend
        :type abm_cluster: str|None
        :return: True if task completed, None if task was discarded (by decorator)
        :rtype: bool|None
        """
        if (abm_cluster is not None and len(nsm_clusters) == 0) or (len(nsm_clusters) > 0 and abm_cluster is None):
            raise ValueError('Both ABM cluster and NSM clusters must be provided')
        if abm_cluster is not None:
            for cluster_name in [abm_cluster] + nsm_clusters:
                try:
                    metadata = ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=cluster_name)
                    if metadata['in_use'] is True:
                        raise ValueError('Cluster {0} has already been claimed'.format(cluster_name))
                except NotFoundException:
                    raise ValueError('Could not find an Arakoon cluster with name: {0}'.format(cluster_name))
        AlbaController._alba_arakoon_checkup(alba_backend_guid=alba_backend_guid,
                                             abm_cluster=abm_cluster,
                                             nsm_clusters=nsm_clusters)
        return True

    @staticmethod
    def _link_plugins(client, data_dir, plugins, cluster_name):
        """
        Create symlinks for the Arakoon plugins to the correct (mounted) partition
        :param client: SSHClient to execute this on
        :type client: SSHClient
        :param data_dir: Directory on which the DB partition resides
        :type data_dir: str
        :param plugins: Plugins to symlink
        :type plugins: list
        :param cluster_name: Name of the Arakoon cluster
        :type cluster_name: str
        :return: None
        :rtype: NoneType
        """
        data_dir = '' if data_dir == '/' else data_dir
        for plugin in plugins:
            client.run(['ln', '-s', '{0}/{1}.cmxs'.format(AlbaController.ARAKOON_PLUGIN_DIR, plugin), ArakoonInstaller.ARAKOON_HOME_DIR.format(data_dir, cluster_name)])

    @staticmethod
    def _alba_arakoon_checkup(alba_backend_guid=None, abm_cluster=None, nsm_clusters=None):
        slaves = StorageRouterList.get_slaves()
        masters = StorageRouterList.get_masters()
        clients = {}
        available_storagerouters = {}
        for storagerouter in masters + slaves:
            try:
                clients[storagerouter] = SSHClient(storagerouter)
                if storagerouter in masters:
                    storagerouter.invalidate_dynamics(['partition_config'])
                    if len(storagerouter.partition_config[DiskPartition.ROLES.DB]) > 0:
                        available_storagerouters[storagerouter] = DiskPartition(storagerouter.partition_config[DiskPartition.ROLES.DB][0])
            except UnableToConnectException:
                AlbaController._logger.warning('Storage Router with IP {0} is not reachable'.format(storagerouter.ip))

        # Cluster creation
        if alba_backend_guid is not None:
            alba_backend = AlbaBackend(alba_backend_guid)
            abm_cluster_name = '{0}-abm'.format(alba_backend.name)

            # ABM Arakoon cluster creation
            if alba_backend.abm_cluster is None:
                metadata = ArakoonInstaller.get_unused_arakoon_metadata_and_claim(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.ABM,
                                                                                  cluster_name=abm_cluster)
                if metadata is None:  # No externally unused clusters found, we create 1 ourselves
                    if not available_storagerouters:
                        raise RuntimeError('Could not find any partitions with DB role')
                    if abm_cluster is not None:
                        raise ValueError('Cluster {0} has been claimed by another process'.format(abm_cluster))
                    AlbaController._logger.info('Creating Arakoon cluster: {0}'.format(abm_cluster_name))
                    storagerouter, partition = available_storagerouters.items()[0]
                    arakoon_installer = ArakoonInstaller(cluster_name=abm_cluster_name)
                    arakoon_installer.create_cluster(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.ABM,
                                                     ip=storagerouter.ip,
                                                     base_dir=partition.folder,
                                                     plugins={AlbaController.ABM_PLUGIN: AlbaController.ALBA_VERSION_GET},
                                                     log_sinks=LogHandler.get_sink_path('arakoon_server'),
                                                     crash_log_sinks=LogHandler.get_sink_path('arakoon_server_crash'))
                    AlbaController._link_plugins(client=clients[storagerouter],
                                                 data_dir=partition.folder,
                                                 plugins=[AlbaController.ABM_PLUGIN],
                                                 cluster_name=abm_cluster_name)
                    arakoon_installer.start_cluster()
                    ports = arakoon_installer.ports[storagerouter.ip]
                    metadata = arakoon_installer.metadata
                else:
                    ports = []
                    storagerouter = None

                abm_cluster_name = metadata['cluster_name']
                AlbaController._logger.info('Claimed {0} managed Arakoon cluster: {1}'.format('externally' if storagerouter is None else 'internally', abm_cluster_name))
                AlbaController._update_abm_client_config(abm_name=abm_cluster_name,
                                                         ip=clients.keys()[0].ip)
                AlbaController._model_service(alba_backend=alba_backend,
                                              cluster_name=abm_cluster_name,
                                              ports=ports,
                                              storagerouter=storagerouter)

            # NSM Arakoon cluster creation
            if len(alba_backend.nsm_clusters) == 0 and nsm_clusters is not None:
                ports = []
                storagerouter = None
                if len(nsm_clusters) > 0:
                    metadatas = []
                    for nsm_cluster in nsm_clusters:
                        metadata = ArakoonInstaller.get_unused_arakoon_metadata_and_claim(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM,
                                                                                          cluster_name=nsm_cluster)
                        if metadata is None:
                            AlbaController._logger.warning('Arakoon cluster {0} has been claimed by another process, reverting...'.format(nsm_cluster))
                            for md in metadatas:
                                ArakoonInstaller(cluster_name=md['cluster_name']).unclaim_cluster()
                            ArakoonInstaller(cluster_name=abm_cluster_name).unclaim_cluster()
                            raise ValueError('Arakoon cluster {0} has been claimed by another process'.format(nsm_cluster))
                        metadatas.append(metadata)
                else:
                    metadata = ArakoonInstaller.get_unused_arakoon_metadata_and_claim(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM)
                    if metadata is None:  # No externally unused clusters found, we create 1 ourselves
                        if not available_storagerouters:
                            raise RuntimeError('Could not find any partitions with DB role')

                        nsm_cluster_name = '{0}-nsm_0'.format(alba_backend.name)
                        AlbaController._logger.info('Creating Arakoon cluster: {0}'.format(nsm_cluster_name))
                        storagerouter, partition = available_storagerouters.items()[0]
                        arakoon_installer = ArakoonInstaller(cluster_name=nsm_cluster_name)
                        arakoon_installer.create_cluster(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM,
                                                         ip=storagerouter.ip,
                                                         base_dir=partition.folder,
                                                         plugins={AlbaController.NSM_PLUGIN: AlbaController.ALBA_VERSION_GET},
                                                         log_sinks=LogHandler.get_sink_path('arakoon_server'),
                                                         crash_log_sinks=LogHandler.get_sink_path('arakoon_server_crash'))
                        AlbaController._link_plugins(client=clients[storagerouter],
                                                     data_dir=partition.folder,
                                                     plugins=[AlbaController.NSM_PLUGIN],
                                                     cluster_name=nsm_cluster_name)
                        arakoon_installer.start_cluster()
                        ports = arakoon_installer.ports[storagerouter.ip]
                        metadata = arakoon_installer.metadata
                    metadatas = [metadata]

                for index, metadata in enumerate(metadatas):
                    nsm_cluster_name = metadata['cluster_name']
                    AlbaController._logger.info('Claimed {0} managed Arakoon cluster: {1}'.format('externally' if storagerouter is None else 'internally', nsm_cluster_name))
                    AlbaController._register_nsm(abm_name=abm_cluster_name,
                                                 nsm_name=nsm_cluster_name,
                                                 ip=clients.keys()[0])
                    AlbaController._model_service(alba_backend=alba_backend,
                                                  cluster_name=nsm_cluster_name,
                                                  ports=ports,
                                                  storagerouter=storagerouter,
                                                  number=index)

        # ABM Cluster extension
        for alba_backend in AlbaBackendList.get_albabackends():
            if alba_backend.abm_cluster is None:
                AlbaController._logger.warning('ALBA Backend {0} does not have an ABM cluster registered'.format(alba_backend.name))
                continue

            abm_cluster_name = alba_backend.abm_cluster.name
            metadata = ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=abm_cluster_name)
            if 0 < len(alba_backend.abm_cluster.abm_services) < len(available_storagerouters) and metadata['internal'] is True:
                current_abm_ips = [abm_service.service.storagerouter.ip for abm_service in alba_backend.abm_cluster.abm_services]
                for storagerouter, partition in available_storagerouters.iteritems():
                    if storagerouter.ip in current_abm_ips:
                        continue
                    arakoon_installer = ArakoonInstaller(cluster_name=abm_cluster_name)
                    arakoon_installer.load()
                    arakoon_installer.extend_cluster(new_ip=storagerouter.ip,
                                                     base_dir=partition.folder,
                                                     log_sinks=LogHandler.get_sink_path('arakoon_server'),
                                                     crash_log_sinks=LogHandler.get_sink_path('arakoon_server_crash'))
                    AlbaController._link_plugins(client=clients[storagerouter],
                                                 data_dir=partition.folder,
                                                 plugins=[AlbaController.ABM_PLUGIN],
                                                 cluster_name=abm_cluster_name)
                    AlbaController._model_service(alba_backend=alba_backend,
                                                  cluster_name=abm_cluster_name,
                                                  ports=arakoon_installer.ports[storagerouter.ip],
                                                  storagerouter=storagerouter)
                    arakoon_installer.restart_cluster_after_extending(new_ip=storagerouter.ip)
                    AlbaController._update_abm_client_config(abm_name=abm_cluster_name,
                                                             ip=storagerouter.ip)
                    current_abm_ips.append(storagerouter.ip)

    @staticmethod
    @add_hooks('nodetype', 'demote')
    def _on_demote(cluster_ip, master_ip, offline_node_ips=None):
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

        for alba_backend in AlbaBackendList.get_albabackends():
            if alba_backend.abm_cluster is None:
                raise ValueError('ALBA Backend {0} does not have an ABM cluster registered'.format(alba_backend.name))

            internal = alba_backend.abm_cluster.abm_services[0].service.is_internal
            abm_cluster_name = alba_backend.abm_cluster.name
            if internal is True:
                # Remove the node from the ABM
                AlbaController._logger.info('Shrinking ABM for Backend {0}'.format(alba_backend.name))
                abm_storagerouter_ips = [abm_service.service.storagerouter.ip for abm_service in alba_backend.abm_cluster.abm_services]
                abm_remaining_ips = list(set(abm_storagerouter_ips).difference(set(offline_node_ips)))
                if len(abm_remaining_ips) == 0:
                    raise RuntimeError('No other available nodes found in the ABM cluster')

                if cluster_ip in abm_storagerouter_ips:
                    AlbaController._logger.info('* Shrink ABM cluster')
                    arakoon_installer = ArakoonInstaller(cluster_name=abm_cluster_name)
                    arakoon_installer.shrink_cluster(removal_ip=cluster_ip,
                                                     offline_nodes=offline_node_ips)
                    arakoon_installer.restart_cluster_after_shrinking()

                    AlbaController._logger.info('* Updating ABM client config')
                    AlbaController._update_abm_client_config(abm_name=abm_cluster_name,
                                                             ip=abm_remaining_ips[0])

                    AlbaController._logger.info('* Remove old ABM node from model')
                    abm_service = [abm_service for abm_service in alba_backend.abm_cluster.abm_services if abm_service.service.storagerouter.ip == cluster_ip][0]
                    abm_service.delete()
                    abm_service.service.delete()

                AlbaController._logger.info('Shrinking NSM for Backend {0}'.format(alba_backend.name))
                for nsm_cluster in alba_backend.nsm_clusters:
                    nsm_service_ips = [nsm_service.service.storagerouter.ip for nsm_service in nsm_cluster.nsm_services]
                    if cluster_ip not in nsm_service_ips:
                        # No need to shrink when NSM cluster was not extended over current node
                        continue

                    nsm_service_ips.remove(cluster_ip)
                    nsm_remaining_ips = list(set(nsm_service_ips).difference(set(offline_node_ips)))
                    if len(nsm_remaining_ips) == 0:
                        raise RuntimeError('No other available nodes found in the NSM cluster')

                    # Remove the node from the NSM
                    AlbaController._logger.info('* Shrink NSM cluster {0}'.format(nsm_cluster.name))
                    arakoon_installer = ArakoonInstaller(cluster_name=nsm_cluster.name)
                    arakoon_installer.shrink_cluster(removal_ip=cluster_ip,
                                                     offline_nodes=offline_node_ips)
                    arakoon_installer.restart_cluster_after_shrinking()

                    AlbaController._logger.info('* Updating NSM cluster config to ABM for cluster {0}'.format(nsm_cluster.name))
                    AlbaController._update_nsm(abm_name=abm_cluster_name,
                                               nsm_name=nsm_cluster.name,
                                               ip=nsm_remaining_ips[0])

                    AlbaController._logger.info('* Remove old NSM node from model')
                    nsm_service = [nsm_service for nsm_service in nsm_cluster.nsm_services if nsm_service.service.storagerouter.ip == cluster_ip][0]
                    nsm_service.delete()
                    nsm_service.service.delete()

    @staticmethod
    @add_hooks('noderemoval', 'remove')
    def _on_remove(cluster_ip, complete_removal):
        """
        A node is removed
        :param cluster_ip: IP of the node being removed
        :type cluster_ip: str
        :param complete_removal: Completely remove the ASDs and ASD-manager or only unlink
        :type complete_removal: bool
        :return: None
        """
        for alba_backend in AlbaBackendList.get_albabackends():
            for abm_service in alba_backend.abm_cluster.abm_services:
                if abm_service.service.is_internal is True and abm_service.service.storagerouter.ip == cluster_ip:
                    abm_service.delete()
                    abm_service.service.delete()
                    break
            for nsm_cluster in alba_backend.nsm_clusters:
                for nsm_service in nsm_cluster.nsm_services:
                    if nsm_service.service.is_internal is True and nsm_service.service.storagerouter.ip == cluster_ip:
                        nsm_service.delete()
                        nsm_service.service.delete()
                        break

        storage_router = StorageRouterList.get_by_ip(cluster_ip)
        if storage_router is None:
            AlbaController._logger.warning('Failed to retrieve StorageRouter with IP {0} from model'.format(cluster_ip))
            return

        if storage_router.alba_node is not None:
            alba_node = storage_router.alba_node
            if complete_removal is True:
                from ovs.lib.albanode import AlbaNodeController
                AlbaNodeController.remove_node(node_guid=storage_router.alba_node.guid)
            else:
                alba_node.storagerouter = None
                alba_node.save()

        for service in storage_router.services:
            service.delete()

    @staticmethod
    @add_hooks('noderemoval', 'validate_removal')
    def _validate_removal(cluster_ip):
        """
        Validate whether the specified StorageRouter can be removed
        :param cluster_ip: IP of the StorageRouter to validate for removal
        :type cluster_ip: str
        :return: None
        """
        for alba_backend in AlbaBackendList.get_albabackends():
            if alba_backend.abm_cluster is None:
                raise ValueError('ALBA Backend {0} does not have an ABM cluster registered'.format(alba_backend.name))
            if len(alba_backend.abm_cluster.abm_services) == 0:
                raise ValueError('ALBA Backend {0} does not have any registered ABM services'.format(alba_backend.name))

            if alba_backend.abm_cluster.abm_services[0].service.is_internal is False:
                continue

            abm_service_ips = [abm_service.service.storagerouter.ip for abm_service in alba_backend.abm_cluster.abm_services]
            if cluster_ip in abm_service_ips and len(abm_service_ips) == 1:
                raise RuntimeError('Node to remove is only node left in the ABM cluster for ALBA Backend {0}'.format(alba_backend.name))

            for nsm_cluster in alba_backend.nsm_clusters:
                nsm_service_ips = [nsm_service.service.storagerouter.ip for nsm_service in nsm_cluster.nsm_services]
                if cluster_ip in nsm_service_ips and len(nsm_service_ips) == 1:
                    raise RuntimeError('Node to remove is only node left in NSM cluster {0} for ALBA Backend {1}'.format(nsm_cluster.number, alba_backend.name))

    @staticmethod
    @add_hooks('noderemoval', 'validate_asd_removal')
    def _validate_asd_removal(storage_router_ip):
        """
        Do some validations before removing a node
        :param storage_router_ip: IP of the node trying to be removed
        :type storage_router_ip: str
        :return: Information about ASD safety
        :rtype: dict
        """
        storage_router = StorageRouterList.get_by_ip(storage_router_ip)
        if storage_router is None:
            raise RuntimeError('Failed to retrieve the StorageRouter with IP {0}'.format(storage_router_ip))

        asd_ids = {}
        if storage_router.alba_node is None:
            return {'confirm': False}

        for disk in storage_router.alba_node.disks:
            for osd in disk.osds:
                if osd.alba_backend_guid not in asd_ids:
                    asd_ids[osd.alba_backend_guid] = []
                asd_ids[osd.alba_backend_guid].append(osd.osd_id)

        confirm = False
        messages = []
        for alba_backend_guid, asd_ids in asd_ids.iteritems():
            alba_backend = AlbaBackend(alba_backend_guid)
            safety = AlbaController.calculate_safety(alba_backend_guid=alba_backend_guid, removal_osd_ids=asd_ids)
            if safety['lost'] > 0:
                confirm = True
                messages.append('The removal of this StorageRouter will cause data loss on Backend {0}'.format(alba_backend.name))
            elif safety['critical'] > 0:
                confirm = True
                messages.append('The removal of this StorageRouter brings data at risk on Backend {0}. Loosing more disks will cause data loss.'.format(alba_backend.name))
        return {'confirm': confirm,
                'question': '\n'.join(sorted(messages)) + '\nAre you sure you want to continue?'}

    @staticmethod
    @ovs_task(name='alba.nsm_checkup', schedule=Schedule(minute='45', hour='*'), ensure_single_info={'mode': 'CHAINED'})
    def nsm_checkup(allow_offline=False, alba_backend_guid=None, min_nsms=1, additional_nsms=None):
        """
        Validates the current NSM setup/configuration and takes actions where required.
        Assumptions:
        * A 2 node NSM is considered safer than a 1 node NSM.
        * When adding an NSM, the nodes with the least amount of NSM participation are preferred

        :param allow_offline: Ignore offline nodes
        :type allow_offline: bool
        :param alba_backend_guid: Run for a specific ALBA Backend
        :type alba_backend_guid: str
        :param min_nsms: Minimum amount of NSM hosts that need to be provided
        :type min_nsms: int
        :param additional_nsms: Information about the additional clusters to claim (and create for internally managed Arakoon clusters)
        :type additional_nsms: dict
        :return: None
        """
        # Validations
        if min_nsms < 1:
            raise ValueError('Minimum amount of NSM clusters must be 1 or more')

        additional_nsm_names = []
        additional_nsm_amount = 0
        if additional_nsms is not None:
            additional_nsm_names = additional_nsms.get('names', [])
            additional_nsm_amount = additional_nsms.get('amount')

            if alba_backend_guid is None:
                raise ValueError('Additional NSMs can only be configured for a specific ALBA Backend')
            if not isinstance(additional_nsms, dict):
                raise ValueError("'additional_nsms' must be of type 'dict'")
            if not isinstance(additional_nsm_names, list):
                raise ValueError("'additional_nsm_names' must be of type 'list'")
            if additional_nsm_amount is None or not isinstance(additional_nsm_amount, int):
                raise ValueError('Amount of additional NSM clusters to deploy must be specified and 0 or more')

            if min_nsms > 1 and additional_nsm_amount > 0:
                raise ValueError("'min_nsms' and 'additional_nsms' are mutually exclusive")

            for cluster_name in additional_nsm_names:
                try:
                    ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=cluster_name)
                except NotFoundException:
                    raise ValueError('Arakoon cluster with name {0} does not exist'.format(cluster_name))

        if alba_backend_guid is None:
            alba_backends = [alba_backend for alba_backend in AlbaBackendList.get_albabackends()
                             if alba_backend.backend.status == 'RUNNING']
        else:
            alba_backend = AlbaBackend(alba_backend_guid)
            alba_backends = [alba_backend]

        for alba_backend in alba_backends:
            if alba_backend.abm_cluster is None:
                raise ValueError('No ABM cluster found for ALBA Backend {0}'.format(alba_backend.name))
            if len(alba_backend.abm_cluster.abm_services) == 0:
                raise ValueError('ALBA Backend {0} does not have any registered ABM services'.format(alba_backend.name))
            if len(alba_backend.nsm_clusters) + additional_nsm_amount > 50:
                raise ValueError('The maximum of 50 NSM Arakoon clusters will be exceeded. Amount of clusters that can be deployed for this ALBA Backend: {0}'.format(50 - len(alba_backend.nsm_clusters)))
            # Validate enough externally managed Arakoon clusters are available
            if alba_backend.abm_cluster.abm_services[0].service.is_internal is False:
                unused_cluster_names = set([cluster_info['cluster_name'] for cluster_info in ArakoonInstaller.get_unused_arakoon_clusters(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM)])
                if len(unused_cluster_names) < additional_nsm_amount:
                    raise ValueError('The amount of additional NSM Arakoon clusters to claim ({0}) exceeds the amount of available NSM Arakoon clusters ({1})'.format(additional_nsm_amount, len(unused_cluster_names)))
                if set(additional_nsm_names).difference(unused_cluster_names):
                    raise ValueError('Some of the provided cluster_names have already been claimed before')

        # Create / extend clusters
        safety = Configuration.get('/ovs/framework/plugins/alba/config|nsm.safety')
        maxload = Configuration.get('/ovs/framework/plugins/alba/config|nsm.maxload')
        failed_backends = []
        for alba_backend in alba_backends:
            try:
                # Gather information
                abm_cluster_name = alba_backend.abm_cluster.name
                AlbaController._logger.debug('Ensuring NSM safety for Backend {0}'.format(abm_cluster_name))

                internal = alba_backend.abm_cluster.abm_services[0].service.is_internal
                nsm_loads = {}
                nsm_storagerouter = {}
                for nsm_cluster in alba_backend.nsm_clusters:
                    nsm_loads[nsm_cluster.number] = AlbaController._get_load(nsm_cluster)
                    if internal is True:
                        for nsm_service in nsm_cluster.nsm_services:
                            if nsm_service.service.storagerouter not in nsm_storagerouter:
                                nsm_storagerouter[nsm_service.service.storagerouter] = 0
                            nsm_storagerouter[nsm_service.service.storagerouter] += 1

                if internal is True:
                    for abm_service in alba_backend.abm_cluster.abm_services:
                        if abm_service.service.storagerouter not in nsm_storagerouter:
                            nsm_storagerouter[abm_service.service.storagerouter] = 0

                # Validate connectivity of all potential StorageRouters
                clients = {}
                for storagerouter in nsm_storagerouter:
                    try:
                        clients[storagerouter] = SSHClient(endpoint=storagerouter)
                    except UnableToConnectException:
                        if allow_offline is True:
                            AlbaController._logger.debug('Storage Router with IP {0} is not reachable'.format(storagerouter.ip))
                        else:
                            raise RuntimeError('Not all StorageRouters are reachable')

                if internal is True:
                    # Extend existing NSM clusters if safety not met
                    for nsm_cluster in alba_backend.nsm_clusters:
                        AlbaController._logger.debug('Processing NSM {0}'.format(nsm_cluster.number))
                        # Check amount of nodes
                        if len(nsm_cluster.nsm_services) < safety:
                            AlbaController._logger.debug('Insufficient nodes, extending if possible')
                            # Not enough nodes, let's see what can be done
                            current_sr_ips = [nsm_service.service.storagerouter.ip for nsm_service in nsm_cluster.nsm_services]
                            available_srs = [storagerouter for storagerouter in nsm_storagerouter if storagerouter.ip not in current_sr_ips]
                            # As long as there are available StorageRouters and still not enough StorageRouters configured
                            while len(available_srs) > 0 and len(current_sr_ips) < safety:
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
                                    raise RuntimeError('Could not determine a candidate StorageRouter')
                                current_sr_ips.append(candidate_sr.ip)
                                available_srs.remove(candidate_sr)
                                # Extend the cluster (configuration, services, ...)
                                AlbaController._logger.debug('  Extending cluster config')
                                candidate_sr.invalidate_dynamics(['partition_config'])
                                partition = DiskPartition(candidate_sr.partition_config[DiskPartition.ROLES.DB][0])
                                arakoon_installer = ArakoonInstaller(cluster_name=nsm_cluster.name)
                                arakoon_installer.load()
                                arakoon_installer.extend_cluster(new_ip=candidate_sr.ip,
                                                                 base_dir=partition.folder,
                                                                 log_sinks=LogHandler.get_sink_path('arakoon_server'),
                                                                 crash_log_sinks=LogHandler.get_sink_path('arakoon_server_crash'))
                                AlbaController._logger.debug('  Linking plugin')
                                AlbaController._link_plugins(client=clients[candidate_sr],
                                                             data_dir=partition.folder,
                                                             plugins=[AlbaController.NSM_PLUGIN],
                                                             cluster_name=nsm_cluster.name)
                                AlbaController._logger.debug('  Model services')
                                AlbaController._model_service(alba_backend=alba_backend,
                                                              cluster_name=nsm_cluster.name,
                                                              ports=arakoon_installer.ports[candidate_sr.ip],
                                                              storagerouter=candidate_sr,
                                                              number=nsm_cluster.number)
                                AlbaController._logger.debug('  Restart sequence')
                                arakoon_installer.restart_cluster_after_extending(new_ip=candidate_sr.ip)
                                AlbaController._update_nsm(abm_name=abm_cluster_name,
                                                           nsm_name=nsm_cluster.name,
                                                           ip=candidate_sr.ip)
                                AlbaController._logger.debug('Node added')

                # Load and minimum nsm hosts
                nsms_to_add = additional_nsm_amount
                load_ok = min(nsm_loads.values()) < maxload
                AlbaController._logger.debug('Currently {0} NSM hosts'.format(len(nsm_loads)))
                if min_nsms > 1:
                    AlbaController._logger.debug('Minimum {0} NSM hosts requested'.format(min_nsms))
                    nsms_to_add = max(0, min_nsms - len(nsm_loads))
                if load_ok:
                    AlbaController._logger.debug('NSM load OK')
                else:
                    AlbaController._logger.debug('NSM load NOT OK')
                    nsms_to_add = max(1, nsms_to_add)
                if nsms_to_add > 0:
                    AlbaController._logger.debug('Trying to add {0} NSM hosts'.format(nsms_to_add))

                # Deploy new NSM clusters
                base_number = max(nsm_loads.keys()) + 1
                for count, number in enumerate(xrange(base_number, base_number + nsms_to_add)):
                    if len(nsm_storagerouter) == 0:  # External clusters
                        AlbaController._logger.debug('Externally managed NSM Arakoon cluster needs to be expanded')
                        nsm_cluster_name = None
                        if count < len(additional_nsm_names):
                            nsm_cluster_name = additional_nsm_names[count]
                        metadata = ArakoonInstaller.get_unused_arakoon_metadata_and_claim(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM,
                                                                                          cluster_name=nsm_cluster_name)
                        if metadata is None:
                            AlbaController._logger.warning('Cannot claim additional NSM clusters, because no clusters are available')
                            break

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
                        nsm_cluster_name = metadata['cluster_name']
                        AlbaController._model_service(alba_backend=alba_backend,
                                                      cluster_name=nsm_cluster_name,
                                                      number=number)
                        AlbaController._register_nsm(abm_name=abm_cluster_name,
                                                     nsm_name=nsm_cluster_name,
                                                     ip=client.ip)
                        AlbaController._logger.debug('Externally managed NSM Arakoon cluster expanded with cluster {0}'.format(nsm_cluster_name))
                    else:  # Internal clusters
                        AlbaController._logger.debug('Adding new NSM')
                        # One of the NSM nodes is overloaded. This means the complete NSM is considered overloaded
                        # Figure out which StorageRouters are the least occupied
                        loads = sorted(nsm_storagerouter.values())[:safety]
                        nsm_cluster_name = '{0}-nsm_{1}'.format(alba_backend.name, number)
                        storagerouters = []
                        for storagerouter in nsm_storagerouter:
                            if nsm_storagerouter[storagerouter] in loads:
                                storagerouters.append(storagerouter)
                            if len(storagerouters) == safety:
                                break
                        # Creating a new NSM cluster
                        for index, storagerouter in enumerate(storagerouters):
                            nsm_storagerouter[storagerouter] += 1
                            storagerouter.invalidate_dynamics(['partition_config'])
                            partition = DiskPartition(storagerouter.partition_config[DiskPartition.ROLES.DB][0])
                            arakoon_installer = ArakoonInstaller(cluster_name=nsm_cluster_name)
                            if index == 0:
                                arakoon_installer.create_cluster(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM,
                                                                 ip=storagerouter.ip,
                                                                 base_dir=partition.folder,
                                                                 plugins={AlbaController.NSM_PLUGIN: AlbaController.ALBA_VERSION_GET},
                                                                 log_sinks=LogHandler.get_sink_path('arakoon_server'),
                                                                 crash_log_sinks=LogHandler.get_sink_path('arakoon_server_crash'))
                            else:
                                arakoon_installer.load()
                                arakoon_installer.extend_cluster(new_ip=storagerouter.ip,
                                                                 base_dir=partition.folder,
                                                                 log_sinks=LogHandler.get_sink_path('arakoon_server'),
                                                                 crash_log_sinks=LogHandler.get_sink_path('arakoon_server_crash'))
                            AlbaController._link_plugins(client=clients[storagerouter],
                                                         data_dir=partition.folder,
                                                         plugins=[AlbaController.NSM_PLUGIN],
                                                         cluster_name=nsm_cluster_name)
                            AlbaController._model_service(alba_backend=alba_backend,
                                                          cluster_name=nsm_cluster_name,
                                                          ports=arakoon_installer.ports[storagerouter.ip],
                                                          storagerouter=storagerouter,
                                                          number=number)
                            if index == 0:
                                arakoon_installer.start_cluster()
                            else:
                                arakoon_installer.restart_cluster_after_extending(new_ip=storagerouter.ip)
                        AlbaController._register_nsm(abm_name=abm_cluster_name,
                                                     nsm_name=nsm_cluster_name,
                                                     ip=storagerouters[0].ip)
                        AlbaController._logger.debug('New NSM ({0}) added'.format(number))
            except Exception:
                AlbaController._logger.exception('NSM Checkup failed for Backend {0}'.format(alba_backend.name))
                failed_backends.append(alba_backend.name)
        if len(failed_backends) > 0:
            raise RuntimeError('Checking NSM failed for ALBA backends: {0}'.format(', '.join(failed_backends)))

    @staticmethod
    @ovs_task(name='alba.calculate_safety')
    def calculate_safety(alba_backend_guid, removal_osd_ids):
        """
        Calculates/loads the safety when a certain set of disks are removed
        :param alba_backend_guid: Guid of the ALBA Backend
        :type alba_backend_guid: str
        :param removal_osd_ids: ASDs to take into account for safety calculation
        :type removal_osd_ids: list
        :return: Amount of good, critical and lost ASDs
        :rtype: dict
        """
        alba_backend = AlbaBackend(alba_backend_guid)
        if alba_backend.abm_cluster is None:
            raise ValueError('ALBA Backend {0} does not have an ABM cluster registered'.format(alba_backend.name))

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
        while True:
            try:
                config = Configuration.get_configuration_path(key=alba_backend.abm_cluster.config_location)
                safety_data = AlbaCLI.run(command='get-disk-safety', config=config, extra_params=extra_parameters)
                break
            except Exception as ex:
                if len(extra_parameters) > 1 and 'unknown osd' in ex.message:
                    match = re.search('osd ([^ "]*)', ex.message)
                    if match is not None:
                        osd_id = match.groups()[0]
                        AlbaController._logger.debug('Getting safety: skipping OSD {0}'.format(osd_id))
                        extra_parameters.remove('--long-id={0}'.format(osd_id))
                        continue
                raise
        result = {'good': 0,
                  'critical': 0,
                  'lost': 0}
        for namespace in safety_data:
            safety = namespace.get('safety')
            if safety is None or safety > 0:
                result['good'] += 1
            elif safety == 0:
                result['critical'] += 1
            else:
                result['lost'] += 1
        return result

    @staticmethod
    def _get_load(nsm_cluster):
        """
        Calculates the load of an NSM node, returning a float percentage
        :param nsm_cluster: NSM cluster to retrieve the load for
        :type nsm_cluster: ovs.dal.hybrids.albansmcluster.NSMCluster
        :return: Load of the NSM service
        :rtype: float
        """
        service_capacity = float(nsm_cluster.capacity)
        if service_capacity < 0:
            return 50.0
        if service_capacity == 0:
            return float('inf')

        config = Configuration.get_configuration_path(key=nsm_cluster.alba_backend.abm_cluster.config_location)
        hosts_data = AlbaCLI.run(command='list-nsm-hosts', config=config)
        host = [host for host in hosts_data if host['id'] == nsm_cluster.name][0]
        usage = host['namespaces_count']
        return round(usage / service_capacity * 100.0, 5)

    @staticmethod
    def _register_nsm(abm_name, nsm_name, ip):
        """
        Register the NSM service to the cluster
        :param abm_name: Name of the ABM cluster
        :type abm_name: str
        :param nsm_name: Name of the NSM cluster
        :type nsm_name: str
        :param ip: IP of node in the cluster to register
        :type ip: str
        :return: None
        """
        nsm_config_file = Configuration.get_configuration_path(ArakoonClusterConfig.CONFIG_KEY.format(nsm_name))
        abm_config_file = Configuration.get_configuration_path(ArakoonClusterConfig.CONFIG_KEY.format(abm_name))
        AlbaCLI.run(command='add-nsm-host',
                    config=abm_config_file,
                    extra_params=[nsm_config_file],
                    client=SSHClient(endpoint=ip))

    @staticmethod
    def _update_nsm(abm_name, nsm_name, ip):
        """
        Update the NSM service
        :param abm_name: Name of the ABM cluster
        :type abm_name: str
        :param nsm_name: Name of the NSM cluster
        :type nsm_name: str
        :param ip: IP of node in the cluster to update
        :type ip: str
        :return: None
        """
        nsm_config_file = Configuration.get_configuration_path(ArakoonClusterConfig.CONFIG_KEY.format(nsm_name))
        abm_config_file = Configuration.get_configuration_path(ArakoonClusterConfig.CONFIG_KEY.format(abm_name))
        AlbaCLI.run(command='update-nsm-host',
                    config=abm_config_file,
                    extra_params=[nsm_config_file],
                    client=SSHClient(endpoint=ip))

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
        abm_config_file = Configuration.get_configuration_path(ArakoonClusterConfig.CONFIG_KEY.format(abm_name))
        client = SSHClient(ip)
        # Try 8 times, 1st time immediately, 2nd time after 2 secs, 3rd time after 4 seconds, 4th time after 8 seconds
        # This will be up to 2 minutes
        # Reason for trying multiple times is because after a cluster has been shrunk or extended,
        # master might not be known, thus updating config might fail
        AlbaCLI.run(command='update-abm-client-config', config=abm_config_file, named_params={'attempts': 8}, client=client)

    @staticmethod
    def _model_service(alba_backend, cluster_name, ports=None, storagerouter=None, number=None):
        """
        Adds service to the model
        :param alba_backend: ALBA Backend with which the service is linked
        :type alba_backend: ovs.dal.hybrids.albabackend.AlbaBackend
        :param cluster_name: Name of the cluster the service belongs to
        :type cluster_name: str
        :param ports: Ports on which the service is listening (None if externally managed service)
        :type ports: list
        :param storagerouter: StorageRouter on which the service has been deployed (None if externally managed service)
        :type storagerouter: ovs.dal.hybrids.storagerouter.StorageRouter
        :param number: Number of the service (Only applicable for NSM services)
        :type number: int
        :return: None
        :rtype: NoneType
        """
        if ports is None:
            ports = []

        if number is None:  # Create ABM Service
            service_name = 'arakoon-{0}-abm'.format(alba_backend.name)
            service_type = ServiceTypeList.get_by_name(ServiceType.SERVICE_TYPES.ALBA_MGR)
            cluster = alba_backend.abm_cluster or ABMCluster()
            junction_service = ABMService()
        else:  # Create NSM Service
            cluster = None
            service_name = 'arakoon-{0}-nsm_{1}'.format(alba_backend.name, number)
            service_type = ServiceTypeList.get_by_name(ServiceType.SERVICE_TYPES.NS_MGR)
            for nsm_cluster in alba_backend.nsm_clusters:
                if nsm_cluster.number == number:
                    cluster = nsm_cluster
                    break
            cluster = cluster or NSMCluster()
            cluster.number = number
            junction_service = NSMService()

        AlbaController._logger.info('Model service: {0}'.format(str(service_name)))
        cluster.name = cluster_name
        cluster.alba_backend = alba_backend
        cluster.config_location = ArakoonClusterConfig.CONFIG_KEY.format(cluster_name)
        cluster.save()

        service = DalService()
        service.name = service_name
        service.type = service_type
        service.ports = ports
        service.storagerouter = storagerouter
        service.save()

        if isinstance(junction_service, ABMService):
            junction_service.abm_cluster = cluster
        else:
            junction_service.nsm_cluster = cluster
        junction_service.service = service
        junction_service.save()

    @staticmethod
    @add_hooks('nodeinstallation', ['firstnode', 'extranode'])  # Arguments: cluster_ip and for extranode also master_ip
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
    @ovs_task(name='alba.link_alba_backends')
    def link_alba_backends(alba_backend_guid, metadata):
        """
        Link a GLOBAL ALBA Backend to a LOCAL or another GLOBAL ALBA Backend
        :param alba_backend_guid: ALBA Backend guid to link another ALBA Backend to
        :type alba_backend_guid: str
        :param metadata: Metadata about the linked ALBA Backend
        :type metadata: dict
        :return: Returns True if the linking of the ALBA Backends went successfully or
                 False if the ALBA Backend to link is in 'decommissioned' state
        :rtype: bool
        """
        Toolbox.verify_required_params(required_params={'backend_connection_info': (dict, {'host': (str, Toolbox.regex_ip),
                                                                                           'port': (int, {'min': 1, 'max': 65535}),
                                                                                           'username': (str, None),
                                                                                           'password': (str, None)}),
                                                        'backend_info': (dict, {'domain_guid': (str, Toolbox.regex_guid, False),
                                                                                'linked_guid': (str, Toolbox.regex_guid),
                                                                                'linked_name': (str, Toolbox.regex_vpool),
                                                                                'linked_preset': (str, Toolbox.regex_preset),
                                                                                'linked_alba_id': (str, Toolbox.regex_guid)})},
                                       actual_params=metadata)

        alba_backend = AlbaBackend(alba_backend_guid)
        if alba_backend.abm_cluster is None:
            raise ValueError('ALBA Backend {0} does not have an ABM cluster registered'.format(alba_backend.name))

        # Verify OSD has already been added
        added = False
        claimed = False
        config = Configuration.get_configuration_path(alba_backend.abm_cluster.config_location)
        all_osds = AlbaCLI.run(command='list-all-osds', config=config)
        linked_alba_id = metadata['backend_info']['linked_alba_id']
        for osd in all_osds:
            if osd.get('long_id') == linked_alba_id:
                if osd.get('decommissioned') is True:
                    return False

                added = True
                claimed = osd.get('alba_id') is not None
                break

        if added is False:
            # Add the OSD
            # Retrieve remote Arakoon configuration
            connection_info = metadata['backend_connection_info']
            ovs_client = OVSClient(ip=connection_info['host'],
                                   port=connection_info['port'],
                                   credentials=(connection_info['username'], connection_info['password']),
                                   cache_store=VolatileFactory.get_client())
            task_id = ovs_client.get('/alba/backends/{0}/get_config_metadata'.format(metadata['backend_info']['linked_guid']))
            successful, arakoon_config = ovs_client.wait_for_task(task_id, timeout=300)
            if successful is False:
                raise RuntimeError('Could not load metadata from environment {0}'.format(ovs_client.ip))

            # Write Arakoon configuration to file
            arakoon_config = ArakoonClusterConfig.convert_config_to(config=arakoon_config, return_type='INI')
            remote_arakoon_config = '/opt/OpenvStorage/arakoon_config_temp'
            with open(remote_arakoon_config, 'w') as arakoon_cfg:
                arakoon_cfg.write(arakoon_config)

            try:
                AlbaCLI.run(command='add-osd',
                            config=config,
                            named_params={'prefix': alba_backend_guid,
                                          'preset': metadata['backend_info']['linked_preset'],
                                          'node-id': metadata['backend_info']['linked_guid'],
                                          'alba-osd-config-url': 'file://{0}'.format(remote_arakoon_config)})
            finally:
                os.remove(remote_arakoon_config)

        if claimed is False:
            # Claim and update model
            AlbaController.add_units(alba_backend_guid=alba_backend_guid, osds={linked_alba_id: None}, metadata=metadata)
        return True

    @staticmethod
    @ovs_task(name='alba.unlink_alba_backends')
    def unlink_alba_backends(target_guid, linked_guid):
        """
        Unlink a LOCAL or GLOBAL ALBA Backend from a GLOBAL ALBA Backend
        :param target_guid: Guid of the GLOBAL ALBA Backend from which a link will be removed
        :type target_guid: str
        :param linked_guid: Guid of the GLOBAL or LOCAL ALBA Backend which will be unlinked (Can be a local or a remote ALBA Backend)
        :type linked_guid: str
        :return: None
        """
        parent = AlbaBackend(target_guid)
        linked_osd = None
        for osd in parent.osds:
            if osd.metadata is not None and osd.metadata['backend_info']['linked_guid'] == linked_guid:
                linked_osd = osd
                break

        if linked_osd is not None:
            AlbaController.remove_units(alba_backend_guid=parent.guid, osd_ids=[linked_osd.osd_id])
            linked_osd.delete()
        parent.invalidate_dynamics()
        parent.backend.invalidate_dynamics()

    @staticmethod
    @ovs_task(name='alba.checkup_maintenance_agents', schedule=Schedule(minute='0', hour='*'), ensure_single_info={'mode': 'CHAINED'})
    def checkup_maintenance_agents():
        """
        Check if requested nr of maintenance agents / Backend is actually present
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
            try:
                _node.client.add_maintenance_service(name=_service_name,
                                                     alba_backend_guid=_abackend.guid,
                                                     abm_name=_abackend.abm_cluster.name)
                return True
            except Exception:
                AlbaController._logger.exception('Could not add maintenance service for {0} on {1}'.format(_abackend.name, _node.ip))
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
                backend_name, service_hash = service_name.split('_', 1)[1].rsplit('-', 1)  # E.g. alba-maintenance_my-backend-a4f7e3c61
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
            if alba_backend.abm_cluster is None:
                AlbaController._logger.warning('ALBA Backend cluster {0} does not have an ABM cluster registered'.format(alba_backend.name))
                continue

            name = alba_backend.name
            AlbaController._logger.info('Generating service work log for {0}'.format(name))
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

            layout_key = AlbaController.AGENTS_LAYOUT_CONFIG_KEY.format(alba_backend.guid)
            layout = None
            if Configuration.exists(layout_key):
                layout = Configuration.get(layout_key)
                AlbaController._logger.debug('Specific layout requested: {0}'.format(layout))
                if not isinstance(layout, list):
                    layout = None
                    AlbaController._logger.warning('* Layout is not a list and will be ignored')
                else:
                    all_node_ids = set(node.node_id for node in all_nodes)
                    layout_set = set(layout)
                    for entry in layout_set - all_node_ids:
                        AlbaController._logger.warning('* Layout contains unknown node {0}'.format(entry))
                    if len(layout_set) == len(layout_set - all_node_ids):
                        AlbaController._logger.warning('* Layout does not contain any known nodes and will be ignored')
                        layout = None

            to_remove = {}
            to_add = {}
            if layout is None:
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
                minimum = 1 if alba_backend.scaling == AlbaBackend.SCALINGS.LOCAL else required_nr
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
            else:
                # Remove services from obsolete nodes
                for node in service_map[name]:
                    if node.node_id not in layout:
                        if node not in to_remove:
                            to_remove[node] = []
                        service_names = service_map[name][node]
                        to_remove[node] += service_names
                        service_map[name][node] = []
                        AlbaController._logger.debug('* Candidates for removal (unspecified node): {0} on {1}'.format(service_names, node.ip))
                # Multiple services on a single node must be cleaned
                for node, service_names in service_map[name].iteritems():
                    if len(service_names) > 1:
                        if node not in to_remove:
                            to_remove[node] = []
                        service_names = service_names[1:]
                        to_remove[node] += service_names
                        service_map[name][node] = service_names[0]
                        AlbaController._logger.debug('* Candidates for removal (too many services on node): {0} on {1}'.format(service_names, node.ip))
                # Add services to required nodes
                for node in all_nodes:
                    if node.node_id in layout and node not in service_map[name]:
                        service_name = _generate_name(name)
                        to_add[node] = service_name
                        AlbaController._logger.debug('* Candidate add (specified node): {0} on {1}'.format(service_name, node.ip))
                        service_map[name][node] = [service_name]

            AlbaController._logger.info('Applying service work log for {0}'.format(name))
            made_changes = False
            for node, services in to_remove.iteritems():
                for service_name in services:
                    # noinspection PyTypeChecker
                    if _remove_service(node, service_name, alba_backend):
                        made_changes = True
                        AlbaController._logger.info('* Removed service {0} on {1}: OK'.format(service_name, node.ip))
                    else:
                        AlbaController._logger.warning('* Removed service {0} on {1}: FAIL'.format(service_name, node.ip))
            for node, service_name in to_add.iteritems():
                # noinspection PyTypeChecker
                if _add_service(node, service_name, alba_backend):
                    made_changes = True
                    AlbaController._logger.info('* Added service {0} on {1}: OK'.format(service_name, node.ip))
                else:
                    AlbaController._logger.warning('* Added service {0} on {1}: FAIL'.format(service_name, node.ip))
            if made_changes is True:
                alba_backend.invalidate_dynamics(['live_status'])
                alba_backend.backend.invalidate_dynamics(['live_status'])

            AlbaController._logger.info('Finished service work log for {0}'.format(name))

    @staticmethod
    @ovs_task(name='alba.verify_namespaces', schedule=Schedule(minute='0', hour='0', day_of_month='1', month_of_year='*/3'))
    def verify_namespaces():
        """
        Verify namespaces for all backends
        """
        AlbaController._logger.info('Verify namespace task scheduling started')

        verification_factor = Configuration.get('/ovs/alba/backends/verification_factor', default=10)
        for alba_backend in AlbaBackendList.get_albabackends():
            if alba_backend.abm_cluster is None:
                raise ValueError('ALBA Backend {0} does not have an ABM cluster registered'.format(alba_backend.name))

            config = Configuration.get_configuration_path(key=alba_backend.abm_cluster.config_location)
            namespaces = AlbaCLI.run(command='list-namespaces', config=config)
            for namespace in namespaces:
                ns_name = namespace['name']
                AlbaController._logger.info('Scheduled namespace {0} for verification'.format(ns_name))
                AlbaCLI.run(command='verify-namespace',
                            config=config,
                            named_params={'factor': verification_factor},
                            extra_params=[ns_name, '{0}_{1}'.format(alba_backend.name, ns_name)])

        AlbaController._logger.info('Verify namespace task scheduling finished')

    @staticmethod
    @add_hooks('backend', 'domains-update')
    def _post_backend_domains_updated(backend_guid):
        """
        Execute this functionality when the Backend Domains have been updated
        :param backend_guid: Guid of the Backend to be updated
        :type backend_guid: str
        :return: None
        """
        backend = Backend(backend_guid)
        backend.alba_backend.invalidate_dynamics('local_summary')

    @staticmethod
    def monitor_arakoon_clusters():
        """
        Get an overview of where the Arakoon clusters for each ALBA Backend have been deployed
        The overview is printed on stdout
        :return: None
        """
        try:
            while True:
                output = ['',
                          'Open vStorage - NSM/ABM debug information',
                          '=========================================',
                          'timestamp: {0}'.format(datetime.datetime.now()),
                          '']
                alba_backends = sorted(AlbaBackendList.get_albabackends(), key=lambda k: k.name)
                for sr in sorted(StorageRouterList.get_storagerouters(), key=lambda k: k.name):
                    if len([service for service in sr.services if service.type.name in [ServiceType.SERVICE_TYPES.NS_MGR, ServiceType.SERVICE_TYPES.ALBA_MGR] and service.storagerouter == sr]) == 0:
                        continue
                    output.append('+ {0} ({1})'.format(sr.name, sr.ip))
                    for alba_backend in alba_backends:
                        is_internal = alba_backend.abm_cluster.abm_services[0].service.is_internal
                        if is_internal is False:
                            output.append('    + ABM (externally managed)')
                        else:
                            abm_service = [abm_service for abm_service in alba_backend.abm_cluster.abm_services if abm_service.service.storagerouter == sr]
                            nsm_clusters = [nsm_cluster for nsm_cluster in alba_backend.nsm_clusters for nsm_service in nsm_cluster.nsm_services if nsm_service.service.storagerouter == sr]
                            if len(abm_service) > 0 or len(nsm_clusters) > 0:
                                output.append('  + {0}'.format(alba_backend.name))
                                if len(abm_service) > 0:
                                    output.append('    + ABM - port {0}'.format(abm_service[0].service.ports))
                            for nsm_cluster in sorted(nsm_clusters, key=lambda k: k.number):
                                load = None
                                try:
                                    load = AlbaController._get_load(nsm_cluster)
                                except:
                                    pass  # Don't print load when Arakoon unreachable
                                load = 'infinite' if load == float('inf') else '{0}%'.format(round(load, 2)) if load is not None else 'unknown'
                                capacity = 'infinite' if float(nsm_cluster.capacity) < 0 else float(nsm_cluster.capacity)
                                for nsm_service in nsm_cluster.nsm_services:
                                    if nsm_service.service.storagerouter != sr:
                                        continue
                                    if is_internal is True:
                                        output.append('    + NSM {0} - port {1} - capacity: {2}, load: {3}'.format(nsm_cluster.number,
                                                                                                                   nsm_service.service.ports,
                                                                                                                   capacity,
                                                                                                                   load))
                                    else:
                                        output.append('    + NSM {0} (externally managed) - capacity: {1}, load: {2}'.format(nsm_cluster.number,
                                                                                                                             capacity,
                                                                                                                             load))
                output += ['',
                           'Press ^C to exit',
                           '']
                print '\x1b[2J\x1b[H' + '\n'.join(output)
                time.sleep(1)
        except KeyboardInterrupt:
            pass
