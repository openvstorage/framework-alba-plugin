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
import logging
import collections
from ovs.constants.albarakoon import NSM_PLUGIN, MAX_NSM_AMOUNT
from ovs.dal.hybrids.albaabmcluster import ABMCluster
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.albansmcluster import NSMCluster
from ovs.dal.hybrids.albas3transactioncluster import S3TransactionCluster
from ovs.dal.hybrids.diskpartition import DiskPartition
from ovs.dal.hybrids.servicetype import ServiceType
from ovs.dal.hybrids.storagerouter import StorageRouter
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.dal.lists.albas3transactionclusterlist import S3TransactionClusterList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs_extensions.constants.framework import PLUGINS_ALBA_CONFIG
from ovs.extensions.db.arakooninstaller import ArakoonInstaller
from ovs.extensions.generic.configuration import Configuration, NotFoundException
from ovs.extensions.generic.sshclient import SSHClient, UnableToConnectException
from ovs.extensions.plugins.albacli import AlbaCLI
from ovs.lib.helpers.alba_arakoon_installer import AlbaArakoonInstaller, ABMInstaller, NSMInstaller, S3TransactionInstaller
from ovs.lib.helpers.decorators import ovs_task
from ovs.lib.helpers.toolbox import Schedule


class AlbaArakoonController(object):

    _logger = logging.getLogger(__name__)

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
            arakoon_clusters = list(Configuration.list('/ovs/arakoon'))
            # Remove the ABM cluster
            ABMInstaller.remove_abm_cluster(alba_backend.abm_cluster, arakoon_clusters)
            # Remove NSM Arakoon clusters and services
            for nsm_cluster in alba_backend.nsm_clusters:
                NSMInstaller.remove_nsm_cluster(nsm_cluster, arakoon_clusters)

    @classmethod
    def get_available_arakoon_storagerouters(cls, ssh_clients=None):
        # type: (Optional[Dict[StorageRouter, SSHClient]]) -> Dict[StorageRouter, DiskPartition]
        """
        Retrieves all Storagerouters which are suitable to deploy Arakoons on
        :return: Set of all Storagerouters that are suitable
        :rtype: Dict[StorageRouter, DiskPartition]
        """
        ssh_clients = ssh_clients or {}
        available_storagerouters = {}
        masters = StorageRouterList.get_masters()
        for storagerouter in masters:
            try:
                partition = AlbaArakoonInstaller.get_db_partition(storagerouter)
                try:
                    if ssh_clients:
                        client = ssh_clients.get(storagerouter)
                    else:
                        client = SSHClient(storagerouter)
                    if client:
                        available_storagerouters[storagerouter] = partition
                except UnableToConnectException:
                    cls._logger.warning('Storage Router with IP {0} is not reachable'.format(storagerouter.ip))
            except ValueError:
                pass  # Ignore storagerouters without DB parition
        return available_storagerouters

    @classmethod
    def _alba_arakoon_checkup(cls, alba_backend_guid=None, abm_cluster=None, nsm_clusters=None):
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
        for storagerouter in masters + slaves:
            try:
                clients[storagerouter] = SSHClient(storagerouter)
            except UnableToConnectException:
                cls._logger.warning('Storage Router with IP {0} is not reachable'.format(storagerouter.ip))
        available_storagerouters = cls.get_available_arakoon_storagerouters(clients)

        # Call here, because this potentially raises error, which should happen before actually making changes
        abm_installer = ABMInstaller(ssh_clients=clients)
        nsm_installer = NSMInstaller(version_str=abm_installer.version_str, ssh_clients=clients)

        # Cluster creation
        if alba_backend_guid is not None:
            alba_backend = AlbaBackend(alba_backend_guid)
            # @todo revisit. This might enforce the ABM name for externals (might be unintended)
            abm_cluster_name = '{0}-abm'.format(alba_backend.name)

            # ABM Arakoon cluster creation
            if alba_backend.abm_cluster is None:
                if abm_cluster:
                    abm_installer.deploy_abm_cluster(alba_backend, abm_cluster_name,
                                                     requested_abm_cluster_name=abm_cluster)
                else:
                    # Fallback to installing the cluster on an available storagerouter
                    if not available_storagerouters:
                        raise RuntimeError('No StorageRouters available to deploy ABM Arakoon cluster on')
                    storagerouter, partition = available_storagerouters.items()[0]
                    abm_installer.deploy_abm_cluster(alba_backend, abm_cluster_name,
                                                     storagerouter=storagerouter)

            # NSM Arakoon cluster creation
            if len(alba_backend.nsm_clusters) == 0:
                if nsm_clusters:
                    nsm_installer.deploy_nsm_cluster(alba_backend, nsm_clusters=nsm_clusters)
                else:
                    if not available_storagerouters:
                        raise RuntimeError('No StorageRouters available to deploy NSM Arakoon cluster on')
                    storagerouter, partition = available_storagerouters.items()[0]
                    nsm_installer.deploy_nsm_cluster(alba_backend, storagerouter=storagerouter)

        # ABM Cluster extension
        for alba_backend in AlbaBackendList.get_albabackends():
            if alba_backend.abm_cluster is None:
                AlbaArakoonController._logger.warning('ALBA Backend {0} does not have an ABM cluster registered'.format(alba_backend.name))
                continue
            cls.ensure_abm_cluster_safety(alba_backend.abm_cluster, available_storagerouters, abm_installer=abm_installer)

    @staticmethod
    @ovs_task(name='alba.scheduled_alba_arakoon_checkup',
              schedule=Schedule(minute='30', hour='*'),
              ensure_single_info={'mode': 'DEFAULT', 'extra_task_names': ['alba.manual_alba_arakoon_checkup']})
    def scheduled_alba_arakoon_checkup():
        # type: () -> None
        """
        Makes sure the ABM Arakoon is on all available master nodes
        :return: None
        """
        AlbaArakoonController._alba_arakoon_checkup()

    @staticmethod
    @ovs_task(name='alba.manual_alba_arakoon_checkup',
              ensure_single_info={'mode': 'DEFAULT', 'extra_task_names': ['alba.scheduled_alba_arakoon_checkup']})
    def manual_alba_arakoon_checkup(alba_backend_guid, nsm_clusters=None, abm_cluster=None):
        # type: (str, Optional[List[str]], Optional[str]) -> Union[bool, None]
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
        if nsm_clusters is None:
            nsm_clusters = []
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

    @staticmethod
    def get_load(nsm_cluster):
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
        try:
            host = [host for host in hosts_data if host['id'] == nsm_cluster.name][0]
        except IndexError:
            raise ValueError('No host data could be retrieved from Alba for NSM cluster {0}'.format(nsm_cluster.name))
        usage = host['namespaces_count']
        return round(usage / service_capacity * 100.0, 5)

    @classmethod
    def get_nsm_loads(cls, alba_backend):
        # type: (AlbaBackend) -> Dict[int, float]
        """
        Get the amount of nsm for every storagerouter
        :param alba_backend: Alba Backend to list nsms for
        :return: An overview of how much load is on each nsm cluster
        :rtype: Dict[int, float]
        """
        nsm_loads = collections.OrderedDict()
        sorted_nsm_clusters = sorted(alba_backend.nsm_clusters, key=lambda k: k.number)
        for nsm_cluster in sorted_nsm_clusters:
            nsm_loads[nsm_cluster.number] = cls.get_load(nsm_cluster)
        return nsm_loads

    @classmethod
    def get_nsms_per_storagerouter(cls, alba_backend):
        # type: (AlbaBackend) -> Dict[StorageRouter, int]
        """
        Get the amount of nsm for every storagerouter
        :param alba_backend: Alba Backend to list nsms for
        :return: An overview of how many NSMs are on each storagerouter
        :rtype: Dict[StorageRouter, int]
        """
        internal = AlbaArakoonInstaller.is_internally_managed(alba_backend)
        nsm_storagerouters = {}
        sorted_nsm_clusters = sorted(alba_backend.nsm_clusters, key=lambda k: k.number)
        for nsm_cluster in sorted_nsm_clusters:
            if internal:
                for nsm_service in nsm_cluster.nsm_services:
                    if nsm_service.service.storagerouter not in nsm_storagerouters:
                        nsm_storagerouters[nsm_service.service.storagerouter] = 0
                    nsm_storagerouters[nsm_service.service.storagerouter] += 1

        # Include ABM hosts as potential candidates to extend to
        if internal:
            for abm_service in alba_backend.abm_cluster.abm_services:
                if abm_service.service.storagerouter not in nsm_storagerouters:
                    nsm_storagerouters[abm_service.service.storagerouter] = 0

        return nsm_storagerouters

    @classmethod
    def ensure_abm_cluster_safety(cls, abm_cluster, available_storagerouters, abm_installer=None):
        # type: (ABMCluster, Dict[StorageRouter, DiskPartition],  Optional[ABMInstaller]) -> None
        """
        Ensure that the ABM cluster is safe and sound
        :param abm_cluster: ABM Cluster object
        :type abm_cluster: ABMCluster
        :param available_storagerouters: All available storagerouters mapped with their DB partition
        :type available_storagerouters:  Dict[StorageRouter, DiskPartition]
        :param abm_installer: The ABMInstaller to use. Defaults to creating a new one
        :type abm_installer: ABMInstaller
        :return: None
        :rtype: NoneType
        """
        abm_installer = abm_installer or ABMInstaller()

        metadata = ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=abm_cluster.name)
        if 0 < len(abm_cluster.abm_services) < len(available_storagerouters) and metadata['internal'] is True:
            current_abm_ips = [abm_service.service.storagerouter.ip for abm_service in abm_cluster.abm_services]
            for storagerouter, partition in available_storagerouters.iteritems():
                if storagerouter.ip in current_abm_ips:
                    continue
                abm_installer.extend_abm_cluster(storagerouter, abm_cluster)
                current_abm_ips.append(storagerouter.ip)

    @classmethod
    def ensure_nsm_cluster_safety(cls, nsm_cluster, nsms_per_storagerouter=None, nsm_installer=None):
        # type: (NSMCluster, Optional[Dict[StorageRouter, int]], Optional[NSMInstaller]) -> None
        """
        Ensure that the NSM clusters are safe and sound
        :param nsm_cluster: NSM Cluster to extend
        :type nsm_cluster: NSMCluster
        :param nsms_per_storagerouter: Amount of NSMs mapped by StorageRouter
        :type nsms_per_storagerouter: Dict[StorageRouter, int]
        :param nsm_installer: NSMInstaller instance to use. Defaults to creating a new one
        :type nsm_installer: NSMInstaller
        """
        nsm_installer = nsm_installer or NSMInstaller()
        alba_backend = nsm_cluster.alba_backend
        nsms_per_storagerouter = nsms_per_storagerouter if nsms_per_storagerouter is not None else cls.get_nsms_per_storagerouter(alba_backend)

        safety = Configuration.get('/ovs/framework/plugins/alba/config|nsm.safety')
        AlbaArakoonController._logger.debug('NSM safety is configured at: {0}'.format(safety))

        # Check amount of nodes
        if len(nsm_cluster.nsm_services) < safety:
            cls._logger.info('ALBA Backend {0} - Extending if possible'.format(alba_backend.name))
            current_sr_hosts = [nsm_service.service.storagerouter for nsm_service in nsm_cluster.nsm_services]
            available_sr_hosts = [storagerouter for storagerouter in nsms_per_storagerouter if storagerouter not in current_sr_hosts]
            while len(available_sr_hosts) > 0 and len(current_sr_hosts) < safety:
                candidate_sr = None
                candidate_load = None
                for storagerouter in available_sr_hosts:
                    # Determine the least NSM-loaded Storagerouter to extend to
                    storagerouter_nsm_load = nsms_per_storagerouter[storagerouter]
                    if candidate_load is None or storagerouter_nsm_load < candidate_load:
                        candidate_sr = storagerouter
                        candidate_load = storagerouter_nsm_load
                if candidate_sr is None or candidate_load is None:
                    raise RuntimeError('Could not determine a candidate StorageRouter')
                current_sr_hosts.append(candidate_sr.ip)
                available_sr_hosts.remove(candidate_sr)
                # Extend the cluster (configuration, services, ...)
                nsm_installer.extend_nsm_cluster(candidate_sr, nsm_cluster)

    @classmethod
    def ensure_nsm_clusters_load(cls, alba_backend, nsms_per_storagerouter=None, min_internal_nsms=1, external_nsm_cluster_names=None, version_str=None, ssh_clients=None):
        # type: (AlbaBackend, Optional[Dict[StorageRouter, int]], Optional[int], Optional[List[str], Optional[str]], Optional[StorageRouter, SSHClient]) -> None
        """
        Ensure that all NSM clusters are not overloaded
        :param alba_backend: Alba Backend to ensure NSM Cluster load for
        :type alba_backend: AlbaBackend
        :param nsms_per_storagerouter: Amount of NSMs mapped by StorageRouter
        :type nsms_per_storagerouter: Dict[StorageRouter, int]
        :param min_internal_nsms: Minimum amount of NSM hosts that need to be provided
        :type min_internal_nsms: int
        :param external_nsm_cluster_names: Information about the additional clusters to claim (only for externally managed Arakoon clusters)
        :type external_nsm_cluster_names: list
        :param version_str: Alba version string
        :type version_str: str
        :param ssh_clients: SSHClients to use
        :type ssh_clients: Dict[Storagerouter, SSHClient]
        :return: None
        :rtype: NoneType
        """
        if ssh_clients is None:
            ssh_clients = {}
        if external_nsm_cluster_names is None:
            external_nsm_cluster_names = []

        nsms_per_storagerouter = nsms_per_storagerouter if nsms_per_storagerouter is not None else cls.get_nsms_per_storagerouter(alba_backend)
        version_str = version_str or AlbaArakoonInstaller.get_alba_version_string()
        nsm_loads = cls.get_nsm_loads(alba_backend)
        internal = AlbaArakoonInstaller.is_internally_managed(alba_backend)
        abm_cluster_name = alba_backend.abm_cluster.name

        safety = Configuration.get('/ovs/framework/plugins/alba/config|nsm.safety')
        maxload = Configuration.get('/ovs/framework/plugins/alba/config|nsm.maxload')

        overloaded = min(nsm_loads.values()) >= maxload
        if not overloaded:
            # At least 1 NSM is not overloaded yet
            AlbaArakoonController._logger.debug('ALBA Backend {0} - NSM load OK'.format(alba_backend.name))
            if internal:
                # When load is not OK, deploy at least 1 additional NSM
                nsms_to_add = max(0, min_internal_nsms - len(nsm_loads))
            else:
                nsms_to_add = len(external_nsm_cluster_names)
            if nsms_to_add == 0:
                return
        else:
            AlbaArakoonController._logger.warning('ALBA Backend {0} - NSM load is NOT OK'.format(alba_backend.name))
            if internal:
                # When load is not OK, deploy at least 1 additional NSM
                nsms_to_add = max(1, min_internal_nsms - len(nsm_loads))
            else:
                # For externally managed clusters we only claim the specified clusters, if none provided, we just log it
                nsms_to_add = len(external_nsm_cluster_names)
                if nsms_to_add == 0:
                    cls._logger.critical('ALBA Backend {0} - All NSM clusters are overloaded'.format(alba_backend.name))
                    return

        # Deploy new (internal) or claim existing (external) NSM clusters
        cls._logger.debug('ALBA Backend {0} - Currently {1} NSM cluster{2}'.format(alba_backend.name, len(nsm_loads), '' if len(nsm_loads) == 1 else 's'))
        AlbaArakoonController._logger.debug('ALBA Backend {0} - Trying to add {1} NSM cluster{2}'.format(alba_backend.name, nsms_to_add, '' if nsms_to_add == 1 else 's'))
        base_number = max(nsm_loads.keys()) + 1
        for index, number in enumerate(xrange(base_number, base_number + nsms_to_add)):
            if not internal:
                # External clusters
                master_client = None
                if not ssh_clients:
                    for storagerouter in StorageRouterList.get_masters():
                        try:
                            master_client = SSHClient(storagerouter)
                        except UnableToConnectException:
                            cls._logger.warning('StorageRouter {0} with IP {1} is not reachable'.format(storagerouter.name, storagerouter.ip))
                else:
                    for storagerouter, ssh_client in ssh_clients.iteritems():
                        if storagerouter.node_type == 'MASTER':
                            master_client = ssh_client
                if not master_client:
                    raise ValueError('Could not find an online master node')
                # @todo this might raise an indexerror?
                nsm_cluster_name = external_nsm_cluster_names[index]
                cls._logger.debug('ALBA Backend {0} - Claiming NSM cluster {1}'.format(alba_backend.name, nsm_cluster_name))
                metadata = ArakoonInstaller.get_unused_arakoon_metadata_and_claim(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM,
                                                                                  cluster_name=nsm_cluster_name)
                if metadata is None:
                    cls._logger.critical('ALBA Backend {0} - NSM cluster with name {1} could not be found'.format(alba_backend.name, nsm_cluster_name))
                    continue

                cls._logger.debug('ALBA Backend {0} - Modeling services'.format(alba_backend.name))
                AlbaArakoonInstaller.model_arakoon_service(alba_backend=alba_backend, cluster_name=nsm_cluster_name, number=number)
                cls._logger.debug('ALBA Backend {0} - Registering NSM'.format(alba_backend.name))
                NSMInstaller.register_nsm(abm_name=abm_cluster_name,
                                          nsm_name=nsm_cluster_name,
                                          ip=master_client.ip)
                AlbaArakoonController._logger.debug('ALBA Backend {0} - Extended cluster'.format(alba_backend.name))
            else:
                # Internal clusters
                nsm_cluster_name = '{0}-nsm_{1}'.format(alba_backend.name, number)
                cls._logger.debug('ALBA Backend {0} - Adding NSM cluster {1}'.format(alba_backend.name, nsm_cluster_name))

                # One of the NSM nodes is overloaded. This means the complete NSM is considered overloaded
                # Figure out which StorageRouters are the least occupied
                loads = sorted(nsms_per_storagerouter.values())[:safety]
                storagerouters = []
                for storagerouter, load in nsms_per_storagerouter.iteritems():
                    if load in loads:
                        storagerouters.append(storagerouter)
                    if len(storagerouters) == safety:
                        break
                # Creating a new NSM cluster
                for sub_index, storagerouter in enumerate(storagerouters):
                    nsms_per_storagerouter[storagerouter] += 1
                    partition = AlbaArakoonInstaller.get_db_partition(storagerouter)
                    arakoon_installer = ArakoonInstaller(cluster_name=nsm_cluster_name)
                    # @todo Use deploy and extend code. (Disable register nsm in those parts)
                    if sub_index == 0:
                        arakoon_installer.create_cluster(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM,
                                                         ip=storagerouter.ip,
                                                         base_dir=partition.folder,
                                                         plugins={NSM_PLUGIN: version_str})
                    else:
                        cls._logger.debug('ALBA Backend {0} - Extending NSM cluster {1}'.format(alba_backend.name, nsm_cluster_name))
                        arakoon_installer.load()
                        arakoon_installer.extend_cluster(new_ip=storagerouter.ip,
                                                         base_dir=partition.folder,
                                                         plugins={NSM_PLUGIN: version_str})
                    cls._logger.debug('ALBA Backend {0} - Linking plugins'.format(alba_backend.name))
                    ssh_client = ssh_clients.get(storagerouter) or SSHClient(StorageRouter)
                    AlbaArakoonInstaller.link_plugins(client=ssh_client, data_dir=partition.folder,
                                                      plugins=[NSM_PLUGIN], cluster_name=nsm_cluster_name)
                    cls._logger.debug('ALBA Backend {0} - Modeling services'.format(alba_backend.name))
                    AlbaArakoonInstaller.model_arakoon_service(alba_backend=alba_backend,
                                                               cluster_name=nsm_cluster_name,
                                                               ports=arakoon_installer.ports[storagerouter.ip],
                                                               storagerouter=storagerouter,
                                                               number=number)
                    if sub_index == 0:
                        cls._logger.debug('ALBA Backend {0} - Starting cluster'.format(alba_backend.name))
                        arakoon_installer.start_cluster()
                    else:
                        AlbaArakoonController._logger.debug('ALBA Backend {0} - Restarting cluster'.format(alba_backend.name))
                        arakoon_installer.restart_cluster_after_extending(new_ip=storagerouter.ip)
                cls._logger.debug('ALBA Backend {0} - Registering NSM'.format(alba_backend.name))
                NSMInstaller.register_nsm(abm_name=abm_cluster_name,
                                          nsm_name=nsm_cluster_name,
                                          ip=storagerouters[0].ip)
                cls._logger.debug('ALBA Backend {0} - Added NSM cluster {1}'.format(alba_backend.name, nsm_cluster_name))

    @staticmethod
    @ovs_task(name='alba.nsm_checkup', schedule=Schedule(minute='45', hour='*'), ensure_single_info={'mode': 'CHAINED'})
    def nsm_checkup(alba_backend_guid=None, min_internal_nsms=1, external_nsm_cluster_names=None):
        # type: (Optional[str], Optional[int], Optional[List[str]]) -> None
        """
        Validates the current NSM setup/configuration and takes actions where required.
        Assumptions:
        * A 2 node NSM is considered safer than a 1 node NSM.
        * When adding an NSM, the nodes with the least amount of NSM participation are preferred

        :param alba_backend_guid: Run for a specific ALBA Backend
        :type alba_backend_guid: str
        :param min_internal_nsms: Minimum amount of NSM hosts that need to be provided
        :type min_internal_nsms: int
        :param external_nsm_cluster_names: Information about the additional clusters to claim (only for externally managed Arakoon clusters)
        :type external_nsm_cluster_names: list
        :return: None
        :rtype: NoneType
        """
        ###############
        # Validations #
        ###############
        if external_nsm_cluster_names is None:
            external_nsm_cluster_names = []
        AlbaArakoonController._logger.info('NSM checkup started')
        if min_internal_nsms < 1:
            raise ValueError('Minimum amount of NSM clusters must be 1 or more')

        if not isinstance(external_nsm_cluster_names, list):
            raise ValueError("'external_nsm_cluster_names' must be of type 'list'")

        if len(external_nsm_cluster_names) > 0:
            if alba_backend_guid is None:
                raise ValueError('Additional NSMs can only be configured for a specific ALBA Backend')
            if min_internal_nsms > 1:
                raise ValueError("'min_internal_nsms' and 'external_nsm_cluster_names' are mutually exclusive")

            external_nsm_cluster_names = list(set(external_nsm_cluster_names))  # Remove duplicate cluster names
            for cluster_name in external_nsm_cluster_names:
                try:
                    ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=cluster_name)
                except NotFoundException:
                    raise ValueError('Arakoon cluster with name {0} does not exist'.format(cluster_name))

        if alba_backend_guid is None:
            alba_backends = [alba_backend for alba_backend in AlbaBackendList.get_albabackends() if alba_backend.backend.status == 'RUNNING']
        else:
            alba_backends = [AlbaBackend(alba_backend_guid)]

        masters = StorageRouterList.get_masters()
        storagerouters = set()
        for alba_backend in alba_backends:
            if alba_backend.abm_cluster is None:
                raise ValueError('No ABM cluster found for ALBA Backend {0}'.format(alba_backend.name))
            if len(alba_backend.abm_cluster.abm_services) == 0:
                raise ValueError('ALBA Backend {0} does not have any registered ABM services'.format(alba_backend.name))
            if len(alba_backend.nsm_clusters) + len(external_nsm_cluster_names) > MAX_NSM_AMOUNT:
                raise ValueError('The maximum of {0} NSM Arakoon clusters will be exceeded. Amount of clusters that can be deployed for this ALBA Backend: {1}'.format(MAX_NSM_AMOUNT, MAX_NSM_AMOUNT - len(alba_backend.nsm_clusters)))
            # Validate enough externally managed Arakoon clusters are available
            if alba_backend.abm_cluster.abm_services[0].service.is_internal is False:
                unused_cluster_names = set([cluster_info['cluster_name'] for cluster_info in ArakoonInstaller.get_unused_arakoon_clusters(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM)])
                if set(external_nsm_cluster_names).difference(unused_cluster_names):
                    raise ValueError('Some of the provided cluster_names have already been claimed before')
                storagerouters.update(set(masters))  # For externally managed we need an available master node
            else:
                for abm_service in alba_backend.abm_cluster.abm_services:  # For internally managed we need all StorageRouters online
                    storagerouters.add(abm_service.service.storagerouter)
                for nsm_cluster in alba_backend.nsm_clusters:  # For internally managed we need all StorageRouters online
                    for nsm_service in nsm_cluster.nsm_services:
                        storagerouters.add(nsm_service.service.storagerouter)

        ssh_clients = {}
        for storagerouter in storagerouters:
            try:
                ssh_clients[storagerouter] = SSHClient(endpoint=storagerouter)
            except UnableToConnectException:
                raise RuntimeError('StorageRouter {0} with IP {1} is not reachable'.format(storagerouter.name, storagerouter.ip))

        version_str = AlbaArakoonInstaller.get_alba_version_string()
        nsm_installer = NSMInstaller(version_str=version_str, ssh_clients=ssh_clients)

        ##################
        # Check Clusters #
        ##################
        safety = Configuration.get('{0}|nsm.safety'.format(PLUGINS_ALBA_CONFIG))
        maxload = Configuration.get('{0}|nsm.maxload'.format(PLUGINS_ALBA_CONFIG))

        AlbaArakoonController._logger.debug('NSM safety is configured at: {0}'.format(safety))
        AlbaArakoonController._logger.debug('NSM max load is configured at: {0}'.format(maxload))

        master_client = None
        failed_backends = []
        for alba_backend in alba_backends:
            try:
                # Gather information
                AlbaArakoonController._logger.info('ALBA Backend {0} - Ensuring NSM safety'.format(alba_backend.name))

                internal = AlbaArakoonInstaller.is_internally_managed(alba_backend)
                nsm_loads = AlbaArakoonController.get_nsm_loads(alba_backend)
                nsm_storagerouters = AlbaArakoonController.get_nsms_per_storagerouter(alba_backend)
                sorted_nsm_clusters = sorted(alba_backend.nsm_clusters, key=lambda k: k.number)

                if not internal and len(external_nsm_cluster_names) > 0:
                    for sr, cl in ssh_clients.iteritems():
                        if sr.node_type == 'MASTER':
                            master_client = cl
                            break
                    if master_client is None:
                        # Internal is False and we specified the NSM clusters to claim, but no MASTER nodes online
                        raise ValueError('Could not find an online master node')

                AlbaArakoonController._logger.debug('ALBA Backend {0} - Arakoon clusters are {1} managed'.format(alba_backend.name, 'internally' if internal is True else 'externally'))
                for nsm_number, nsm_load in nsm_loads.iteritems():
                    AlbaArakoonController._logger.debug('ALBA Backend {0} - NSM Cluster {1} - Load {2}'.format(alba_backend.name, nsm_number, nsm_load))
                for sr, count in nsm_storagerouters.iteritems():
                    AlbaArakoonController._logger.debug('ALBA Backend {0} - StorageRouter {1} - NSM Services {2}'.format(alba_backend.name, sr.name, count))

                if internal:
                    # Extend existing NSM clusters if safety not met
                    for nsm_cluster in sorted_nsm_clusters:
                        AlbaArakoonController._logger.debug('ALBA Backend {0} - Processing NSM {1} - Expected safety {2} - Current safety {3}'.format(alba_backend.name, nsm_cluster.number, safety, len(nsm_cluster.nsm_services)))
                        AlbaArakoonController.ensure_nsm_cluster_safety(nsm_cluster, nsm_storagerouters, nsm_installer=nsm_installer)
                AlbaArakoonController.ensure_nsm_clusters_load(alba_backend, nsms_per_storagerouter=nsm_storagerouters,
                                                               ssh_clients=ssh_clients, version_str=version_str,
                                                               min_internal_nsms=min_internal_nsms,
                                                               external_nsm_cluster_names=external_nsm_cluster_names)
            except Exception:
                AlbaArakoonController._logger.exception('NSM Checkup failed for Backend {0}'.format(alba_backend.name))
                failed_backends.append(alba_backend.name)

    @classmethod
    def ensure_s3_transaction_safety(cls, s3_cluster, available_storagerouters, s3_installer=None):
        # type: (S3TransactionCluster, Dict[StorageRouter, DiskPartition], Optional[S3TransactionInstaller]) -> None
        """
        Ensure that the S3 transaction cluster is safe and sound
        :param s3_cluster: ABM Cluster object
        :type s3_cluster: ABMCluster
        :param available_storagerouters: All available storagerouters mapped with their DB partition
        :type available_storagerouters:  Dict[StorageRouter, DiskPartition]
        :param s3_installer: The ABMInstaller to use. Defaults to creating a new one
        :type s3_installer: ABMInstaller
        :return: None
        :rtype: NoneType
        """
        s3_transaction_installer = s3_installer or S3TransactionInstaller()

        metadata = ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=s3_cluster.name)
        if 0 < len(s3_cluster.s3_transaction_services) < len(available_storagerouters) and metadata['internal'] is True:
            current_service_ips = [j_service.service.storagerouter.ip for j_service in s3_cluster.s3_transaction_services]
            for storagerouter, partition in available_storagerouters.iteritems():
                if storagerouter.ip in current_service_ips:
                    continue
                s3_transaction_installer.extend_s3_cluster(storagerouter, s3_cluster)
                current_service_ips.append(storagerouter.ip)

    @classmethod
    def configure_s3_transaction_cluster(cls):
        """
        Completely deploys a S3 transaction cluster
        :return: None
        :rtype: NoneType
        """
        s3_transaction_installer = S3TransactionInstaller()
        available_storagerouters = cls.get_available_arakoon_storagerouters()
        if not available_storagerouters:
            raise ValueError('No available storagerouters. Cannot deploy the S3 Transaction Cluster')
        if len(S3TransactionClusterList.get_s3_transaction_clusters()) == 0:
            # Deployment required
            storagerouter, partition = available_storagerouters.items()[0]
            s3_transaction_installer.deploy_s3_cluster(storagerouter)
        s3_transaction_cluster = S3TransactionClusterList.get_s3_transaction_clusters()[0]
        cls.ensure_s3_transaction_safety(s3_transaction_cluster, available_storagerouters)
