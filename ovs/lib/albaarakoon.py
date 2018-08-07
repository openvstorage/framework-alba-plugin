# Copyright (C) 2018 iNuron NV
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
Module which does everything Arakoon related for the Alba plugin
"""
import os
import re
import time
import string
import random
import datetime
import requests
import collections
from ovs.dal.exceptions import ObjectNotFoundException
from ovs.dal.hybrids.albaabmcluster import ABMCluster
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.hybrids.albansmcluster import NSMCluster
from ovs.dal.hybrids.albaosd import AlbaOSD
from ovs.dal.hybrids.backend import Backend
from ovs.dal.hybrids.diskpartition import DiskPartition
from ovs.dal.hybrids.domain import Domain
from ovs.dal.hybrids.j_abmservice import ABMService
from ovs.dal.hybrids.j_nsmservice import NSMService
from ovs.dal.hybrids.service import Service as DalService
from ovs.dal.hybrids.servicetype import ServiceType
from ovs.dal.hybrids.storagerouter import StorageRouter
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.albaosdlist import AlbaOSDList
from ovs.dal.lists.servicetypelist import ServiceTypeList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs_extensions.api.client import OVSClient
from ovs.extensions.db.arakooninstaller import ArakoonClusterConfig, ArakoonInstaller
from ovs.extensions.generic.configuration import Configuration, NotFoundException
from ovs.extensions.generic.logger import Logger
from ovs.extensions.generic.sshclient import SSHClient, UnableToConnectException
from ovs_extensions.generic.toolbox import ExtensionsToolbox
from ovs.extensions.migration.migration.albamigrator import ExtensionMigrator
from ovs.extensions.packages.albapackagefactory import PackageFactory
from ovs.extensions.plugins.albacli import AlbaCLI, AlbaError
from ovs.extensions.storage.volatilefactory import VolatileFactory
from ovs.lib.helpers.decorators import add_hooks, ovs_task
from ovs.lib.helpers.toolbox import Schedule
from ovs.lib.albanode import AlbaNodeController
from ovs.constants.albarakoon import ABM_PLUGIN, NSM_PLUGIN, ARAKOON_PLUGIN_DIR, CONFIG_DEFAULT_NSM_HOSTS_KEY


class AlbaArakoonController(object):

    _logger = Logger('lib')

    @staticmethod
    def abms_reachable(alba_backend):
        # type: (AlbaBackend) -> None
        """
        Check if all ABMs are reachable for a backend
        Only checks internally managed services
        :param alba_backend: AlbaBackend object
        :type alba_backend: AlbaBackend
        :return: None
        :rtype: NoneType
        :raises: RuntimeError: When an ABM could not be reached
        """
        if alba_backend.abm_cluster is not None:
            for abm_service in alba_backend.abm_cluster.abm_services:
                if abm_service.service.is_internal is True:
                    service = abm_service.service
                    try:
                        SSHClient(endpoint=service.storagerouter, username='root')
                    except UnableToConnectException:
                        raise RuntimeError('Node {0} with IP {1} is not reachable'.format(service.storagerouter.name, service.storagerouter.ip))

    @staticmethod
    def nsms_reachable(alba_backend):
        # type: (AlbaBackend) -> None
        """
        Check if all NSMs are reachable for a backend
        Only checks internally managed services
        :param alba_backend: AlbaBackend object
        :type alba_backend: AlbaBackend
        :return: None
        :rtype: NoneType
        :raises: RuntimeError: When an NSM could not be reached
        """
        if alba_backend.abm_cluster is not None:
            for nsm_cluster in alba_backend.nsm_clusters:
                for nsm_service in nsm_cluster.nsm_services:
                    service = nsm_service.service
                    if service.is_internal is True:
                        try:
                            SSHClient(endpoint=service.storagerouter, username='root')
                        except UnableToConnectException:
                            raise RuntimeError('Node {0} with IP {1} is not reachable'.format(service.storagerouter.name, service.storagerouter.ip))

    @classmethod
    def _remove_cluster(cls, cluster_name, internal, associated_junction_services, junction_type, arakoon_clusters=None):
        # type: (str, bool, Iterable[Union[ABMService, NSMService]], type, List[str]) -> None
        """
        Removes an arakoon cluster (either abm or nsm)
        :param cluster_name: Name of the Arakoon cluster to remove
        :type cluster_name: str
        :param internal: Indicator if the Arakoon is managed internally or not
        :type internal: bool
        :param associated_junction_services: All associated modeled services
        :type associated_junction_services: Iterable[Service]
        :param junction_type: Type of the provided junction (used for logging)
        :type junction_type: type
        :param arakoon_clusters: All arakoon clusters up to this point. Defaults to fetching the data
        :type arakoon_clusters: List[str]
        :return: None
        :rtype: NoneType
        """
        if junction_type == ABMService:
            arakoon_id_log = 'ALBA manager'
        elif junction_type == NSMService:
            arakoon_id_log = 'Namespace manager'
        else:
            raise NotImplementedError('No removal logic implemented for {0}'.format(junction_type))

        arakoon_clusters = arakoon_clusters if arakoon_clusters is not None else list(Configuration.list('/ovs/arakoon'))
        if cluster_name in arakoon_clusters:
            # Remove Arakoon cluster
            arakoon_installer = ArakoonInstaller(cluster_name=cluster_name)
            arakoon_installer.load()
            if internal is True:
                AlbaArakoonController._logger.info('Deleting {0} Arakoon cluster {1}'.format(arakoon_id_log, cluster_name))
                arakoon_installer.delete_cluster()
                AlbaArakoonController._logger.info('Deleted {0} Arakoon cluster {1}'.format(arakoon_id_log, cluster_name))
            else:
                AlbaArakoonController._logger.info('Un-claiming {0} Arakoon cluster {1}'.format(arakoon_id_log, cluster_name))
                arakoon_installer.unclaim_cluster()
                AlbaArakoonController._logger.info('Unclaimed {0} Arakoon cluster {1}'.format(arakoon_id_log, cluster_name))

        # Remove Arakoon services
        for j_service in associated_junction_services:  # type: Union[ABMService, NSMService]
            j_service.delete()
            j_service.service.delete()
            if internal is True:
                AlbaArakoonController._logger.info('Removed service {0} on node {1}'.format(j_service.service.name, j_service.service.storagerouter.name))
            else:
                AlbaArakoonController._logger.info('Removed service {0}'.format(j_service.service.name))

    @classmethod
    def remove_alba_arakoon_clusters(cls, alba_backend_guid, validate_clusters_reachable=True):
        # type: (basestring, bool) -> None
        """
        Removes all backend related Arakoon clusters
        :param alba_backend_guid: Guid of the ALBA Backend
        :type alba_backend_guid: str
        :param validate_clusters_reachable: Validate if all clusters are reachable
        :type validate_clusters_reachable: bool
        :return: None
        :rtype: NoneType
        """
        alba_backend = AlbaBackend(alba_backend_guid)
        if validate_clusters_reachable:
            AlbaArakoonController.abms_reachable(alba_backend)
            AlbaArakoonController.nsms_reachable(alba_backend)

        if alba_backend.abm_cluster is not None:
            AlbaArakoonController._logger.debug('Removing clusters for ALBA Backend {0}'.format(alba_backend.name))
            internal = alba_backend.abm_cluster.abm_services[0].service.is_internal
            abm_cluster_name = alba_backend.abm_cluster.name
            arakoon_clusters = list(Configuration.list('/ovs/arakoon'))
            # Remove the ABM clusters
            cls._remove_cluster(abm_cluster_name, internal,
                                associated_junction_services=alba_backend.abm_cluster.abm_services,
                                junction_type=ABMService,
                                arakoon_clusters=arakoon_clusters)
            # Remove the link
            alba_backend.abm_cluster.delete()

            # Remove NSM Arakoon clusters and services
            for nsm_cluster in alba_backend.nsm_clusters:
                cls._remove_cluster(nsm_cluster.name, internal,
                                    associated_junction_services=nsm_cluster.nsm_services,
                                    junction_type=NSMService,
                                    arakoon_clusters=arakoon_clusters)
                nsm_cluster.delete()

    @staticmethod
    def _alba_arakoon_checkup(alba_backend_guid=None, abm_cluster=None, nsm_clusters=None):
        # type: (Optional[str], Optional[str], Optional[List[str]]) -> None
        """
        Creates a new Arakoon cluster if required and extends cluster if possible on all available master nodes
        :param alba_backend_guid: Guid of the ALBA Backend
        :type alba_backend_guid: str
        :param nsm_clusters: NSM clusters for this ALBA Backend
        The code will claim the Arakoon clusters for this backend when provided
        :type nsm_clusters: list[str]
        :param abm_cluster: ABM cluster for this ALBA Backend
        The code will claim the Arakoon cluster for this backend when provided
        :type abm_cluster: str|None
        :return:None
        :rtype: NoneType
        """
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
                AlbaArakoonController._logger.warning('Storage Router with IP {0} is not reachable'.format(storagerouter.ip))

        # Call here, because this potentially raises error, which should happen before actually making changes
        alba_pkg_name, alba_version_cmd = PackageFactory.get_package_and_version_cmd_for(component=PackageFactory.COMP_ALBA)
        version_str = '{0}=`{1}`'.format(alba_pkg_name, alba_version_cmd)

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
                    AlbaArakoonController._logger.info('Creating Arakoon cluster: {0}'.format(abm_cluster_name))
                    storagerouter, partition = available_storagerouters.items()[0]
                    arakoon_installer = ArakoonInstaller(cluster_name=abm_cluster_name)
                    arakoon_installer.create_cluster(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.ABM,
                                                     ip=storagerouter.ip,
                                                     base_dir=partition.folder,
                                                     plugins={ABM_PLUGIN: version_str})
                    AlbaArakoonController._link_plugins(client=clients[storagerouter], data_dir=partition.folder,
                                                        plugins=[ABM_PLUGIN], cluster_name=abm_cluster_name)
                    arakoon_installer.start_cluster()
                    ports = arakoon_installer.ports[storagerouter.ip]
                    metadata = arakoon_installer.metadata
                else:
                    ports = []
                    storagerouter = None

                abm_cluster_name = metadata['cluster_name']
                AlbaArakoonController._logger.info('Claimed {0} managed Arakoon cluster: {1}'.format('externally' if storagerouter is None else 'internally', abm_cluster_name))
                AlbaArakoonController._update_abm_client_config(abm_name=abm_cluster_name, ip=clients.keys()[0].ip)
                AlbaArakoonController._model_service(alba_backend=alba_backend, cluster_name=abm_cluster_name, ports=ports, storagerouter=storagerouter)

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
                            AlbaArakoonController._logger.warning('Arakoon cluster {0} has been claimed by another process, reverting...'.format(nsm_cluster))
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
                        AlbaArakoonController._logger.info('Creating Arakoon cluster: {0}'.format(nsm_cluster_name))
                        storagerouter, partition = available_storagerouters.items()[0]
                        arakoon_installer = ArakoonInstaller(cluster_name=nsm_cluster_name)
                        arakoon_installer.create_cluster(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM,
                                                         ip=storagerouter.ip,
                                                         base_dir=partition.folder,
                                                         plugins={NSM_PLUGIN: version_str})
                        AlbaArakoonController._link_plugins(client=clients[storagerouter],
                                                     data_dir=partition.folder,
                                                     plugins=[NSM_PLUGIN],
                                                     cluster_name=nsm_cluster_name)
                        arakoon_installer.start_cluster()
                        ports = arakoon_installer.ports[storagerouter.ip]
                        metadata = arakoon_installer.metadata
                    metadatas = [metadata]

                for index, metadata in enumerate(metadatas):
                    nsm_cluster_name = metadata['cluster_name']
                    AlbaArakoonController._logger.info('Claimed {0} managed Arakoon cluster: {1}'.format('externally' if storagerouter is None else 'internally', nsm_cluster_name))
                    AlbaArakoonController._register_nsm(abm_name=abm_cluster_name,
                                                 nsm_name=nsm_cluster_name,
                                                 ip=clients.keys()[0])
                    AlbaArakoonController._model_service(alba_backend=alba_backend,
                                                  cluster_name=nsm_cluster_name,
                                                  ports=ports,
                                                  storagerouter=storagerouter,
                                                  number=index)

        # ABM Cluster extension
        for alba_backend in AlbaBackendList.get_albabackends():
            if alba_backend.abm_cluster is None:
                AlbaArakoonController._logger.warning('ALBA Backend {0} does not have an ABM cluster registered'.format(alba_backend.name))
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
                                                     plugins={ABM_PLUGIN: version_str})
                    AlbaArakoonController._link_plugins(client=clients[storagerouter],
                                                 data_dir=partition.folder,
                                                 plugins=[ABM_PLUGIN],
                                                 cluster_name=abm_cluster_name)
                    AlbaArakoonController._model_service(alba_backend=alba_backend,
                                                  cluster_name=abm_cluster_name,
                                                  ports=arakoon_installer.ports[storagerouter.ip],
                                                  storagerouter=storagerouter)
                    arakoon_installer.restart_cluster_after_extending(new_ip=storagerouter.ip)
                    AlbaArakoonController._update_abm_client_config(abm_name=abm_cluster_name,
                                                             ip=storagerouter.ip)
                    current_abm_ips.append(storagerouter.ip)

    @staticmethod
    @ovs_task(name='alba.scheduled_alba_arakoon_checkup',
              schedule=Schedule(minute='30', hour='*'),
              ensure_single_info={'mode': 'DEFAULT', 'extra_task_names': ['alba.manual_alba_arakoon_checkup']})
    def scheduled_alba_arakoon_checkup():
        """
        Makes sure the volumedriver Arakoon is on all available master nodes
        :return: None
        """
        AlbaArakoonController._alba_arakoon_checkup()

    @staticmethod
    @ovs_task(name='alba.manual_alba_arakoon_checkup',
              ensure_single_info={'mode': 'DEFAULT', 'extra_task_names': ['alba.scheduled_alba_arakoon_checkup']})
    def manual_alba_arakoon_checkup(alba_backend_guid, nsm_clusters, abm_cluster=None):
        """
        Creates a new Arakoon cluster if required and extends cluster if possible on all available master nodes
        :param alba_backend_guid: Guid of the ALBA Backend
        :type alba_backend_guid: str
        :param nsm_clusters: NSM clusters for this ALBA Backend
        The code will claim the Arakoon clusters for this backend when provided
        :type nsm_clusters: list[str]
        :param abm_cluster: ABM cluster for this ALBA Backend
        The code will claim the Arakoon cluster for this backend when provided
        :type abm_cluster: str|None
        :return: True if task completed, None if task was discarded (by decorator)
        :rtype: bool|None
        """
        if (abm_cluster is not None and len(nsm_clusters) == 0) or (len(nsm_clusters) > 0 and abm_cluster is None):
            raise ValueError('Both ABM cluster and NSM clusters must be provided')
        if abm_cluster is not None:
            # Check if the requested clusters are available
            for cluster_name in [abm_cluster] + nsm_clusters:
                try:
                    metadata = ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=cluster_name)
                    if metadata['in_use'] is True:
                        raise ValueError('Cluster {0} has already been claimed'.format(cluster_name))
                except NotFoundException:
                    raise ValueError('Could not find an Arakoon cluster with name: {0}'.format(cluster_name))
        AlbaArakoonController._alba_arakoon_checkup(alba_backend_guid=alba_backend_guid, abm_cluster=abm_cluster, nsm_clusters=nsm_clusters)
        return True
