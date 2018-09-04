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
from ovs.constants.albarakoon import ABM_PLUGIN, NSM_PLUGIN, ARAKOON_PLUGIN_DIR
from ovs.dal.hybrids.albaabmcluster import ABMCluster
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.albansmcluster import NSMCluster
from ovs.dal.hybrids.albas3transactioncluster import S3TransactionCluster
from ovs.dal.hybrids.diskpartition import DiskPartition
from ovs.dal.hybrids.j_abmservice import ABMService
from ovs.dal.hybrids.j_nsmservice import NSMService
from ovs.dal.hybrids.j_s3transactionservice import S3TransactionService
from ovs.dal.hybrids.service import Service as DalService
from ovs.dal.hybrids.servicetype import ServiceType
from ovs.dal.hybrids.storagerouter import StorageRouter
from ovs.dal.lists.albas3transactionclusterlist import S3TransactionClusterList
from ovs.dal.lists.servicetypelist import ServiceTypeList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs.extensions.db.arakooninstaller import ArakoonClusterConfig, ArakoonInstaller
from ovs.extensions.generic.configuration import Configuration
from ovs.extensions.generic.logger import Logger
from ovs.extensions.generic.sshclient import SSHClient
from ovs.extensions.packages.albapackagefactory import PackageFactory
from ovs.extensions.plugins.albacli import AlbaCLI


class AlbaArakoonInstaller(object):
    """
    Installs all alba-related Arakoons
    """
    _logger = Logger('lib')

    def __init__(self, version_str=None, ssh_clients=None):
        # type: (Optional[str], Optional[Dict[StorageRouter, SSHClient]]) -> None
        """
        Initialize an AlbaArakoonInstaller
        :param ssh_clients: Dict with SSHClients for every Storagerouter
        This dict is consulted first before building an SSHClient in the code.
        Used to re-use already established connection and avoid failures on connecting to a storagerouter
        :type ssh_clients: Dict[StorageRouter, SSHClient]
        :param version_str: String of the Alba version to use
        :type version_str: str
        """
        if ssh_clients is None:
            ssh_clients = {}

        self.ssh_clients = ssh_clients
        self.version_str = version_str or self.get_alba_version_string()

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
                cls._logger.info('Deleting {0} Arakoon cluster {1}'.format(arakoon_id_log, cluster_name))
                arakoon_installer.delete_cluster()
                cls._logger.info('Deleted {0} Arakoon cluster {1}'.format(arakoon_id_log, cluster_name))
            else:
                cls._logger.info('Un-claiming {0} Arakoon cluster {1}'.format(arakoon_id_log, cluster_name))
                arakoon_installer.unclaim_cluster()
                cls._logger.info('Unclaimed {0} Arakoon cluster {1}'.format(arakoon_id_log, cluster_name))

        # Remove Arakoon services
        for j_service in associated_junction_services:  # type: Union[ABMService, NSMService]
            j_service.delete()
            j_service.service.delete()
            if internal is True:
                cls._logger.info('Removed service {0} on node {1}'.format(j_service.service.name, j_service.service.storagerouter.name))
            else:
                cls._logger.info('Removed service {0}'.format(j_service.service.name))

    @classmethod
    def link_plugins(cls, client, data_dir, plugins, cluster_name):
        # type: (SSHClient, str, List[str], str) -> None
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
            client.run(['ln', '-s', '{0}/{1}.cmxs'.format(ARAKOON_PLUGIN_DIR, plugin),
                        ArakoonInstaller.ARAKOON_HOME_DIR.format(data_dir, cluster_name)])

    @classmethod
    def get_alba_version_string(cls):
        # type: () -> str
        """
        Retrieve the version string of the alba binary
        Potentially raises errors. Better to call it once and pass it along!
        :return: The version string
        :rtype: str
        """
        # Potentially raises errors
        alba_pkg_name, alba_version_cmd = PackageFactory.get_package_and_version_cmd_for(component=PackageFactory.COMP_ALBA)
        return '{0}=`{1}`'.format(alba_pkg_name, alba_version_cmd)

    @staticmethod
    def get_db_partition(storagerouter):
        # type: (StorageRouter) -> DiskPartition
        """
        Get the DB partition of the StorageRouter
        :param storagerouter:
        :return: The DB partition
        :rtype: DiskPartition
        :raises: ValueError when no DB partition is present
        """
        storagerouter.invalidate_dynamics(['partition_config'])
        try:
            return DiskPartition(storagerouter.partition_config[DiskPartition.ROLES.DB][0])
        except IndexError:
            raise ValueError('StorageRouter {0} does not have a DB role. Cannot extend!'.format(storagerouter.guid))

    @classmethod
    def is_internally_managed(cls, alba_backend=None, abm_cluster=None, nsm_cluster=None, s3_cluster=None):
        # type: (Optional[AlbaBackend], Optional[ABMCluster], Optional[NSMCluster], Optional[S3TransactionCluster]) -> bool
        """
        Check if the Alba Arakoons are internally managed for a backend
        :param alba_backend: Alba Backend to check for
        :type alba_backend: AlbaBackend
        :param abm_cluster: ABM Cluster to check
        :type abm_cluster: ABMCluster
        :param nsm_cluster: NSM Cluster to check
        :type nsm_cluster: NSMCluster
        :param s3_cluster: S3 Transaction Cluster to check
        :type s3_cluster: S3TransactionCluster
        :return: True if internally managed
        :rtype: bool
        """
        internal = None
        if abm_cluster:
            internal = len(abm_cluster.abm_services) > 0 and abm_cluster.abm_services[0].service.is_internal
        elif nsm_cluster:
            internal = len(nsm_cluster.nsm_services) > 0 and nsm_cluster.nsm_services[0].service.is_internal
        elif s3_cluster:
            internal = len(s3_cluster.s3_transaction_services) > 0 and s3_cluster.s3_transaction_services[0].service.is_internal
        elif alba_backend:
            internal = alba_backend.abm_cluster and len(alba_backend.abm_cluster.abm_services) > 0 and alba_backend.abm_cluster.abm_services[0].service.is_internal or\
                       len(alba_backend.nsm_clusters) > 0 and len(alba_backend.nsm_clusters[0].nsm_services) > 0 and alba_backend.nsm_clusters[0].nsm_services[0].service.is_internal
        if internal is None:
            raise RuntimeError('Could not determine if the Arakoons are internally managed')
        return internal

    @classmethod
    def model_arakoon_service(cls, alba_backend, cluster_name, ports=None, storagerouter=None, number=None):
        # type: (AlbaBackend, str, Optional[List[int]], Optional[StorageRouter], Optional[int]) -> None
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

        cls._logger.info('Model service: {0}'.format(str(service_name)))
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

    def get_ssh_client(self, storagerouter):
        # type: (StorageRouter) -> SSHClient
        """
        Get an SSHClient for a StorageRotuer
        :param storagerouter: StorageRouter to build a SSHClient for
        :type storagerouter: StorageRouter
        :return: The built or cached SSHClient
        :rtype: SSHClient
        """
        return self.ssh_clients.get(storagerouter) or SSHClient(storagerouter)

    def get_an_ip(self):
        # type: () -> str
        """
        Retrieve an IP in the cluster
        Prioritizes the cached sshclients for election because these have been verified to be online
        :return: An IP
        :rtype: str
        """
        if self.ssh_clients:
            ip = self.ssh_clients.keys()[0].ip
        else:
            ip = StorageRouterList.get_storagerouters()[0].ip
        return ip


class ABMInstaller(AlbaArakoonInstaller):
    def __init__(self, version_str=None, ssh_clients=None):
        super(ABMInstaller, self).__init__(version_str=version_str, ssh_clients=ssh_clients)

    @classmethod
    def update_abm_client_config(cls, abm_name, ip):
        # type: (str, str) -> None
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

    def deploy_abm_cluster(self, alba_backend, abm_cluster_name, requested_abm_cluster_name=None, storagerouter=None):
        # type: (AlbaBackend, str, Optional[str], Optional[StorageRouter]) -> None
        """
        Deploy an ABM Cluster
        Will try to claim an external one if one is available
        :param alba_backend: ALBA Backend to create the ABM cluster for
        :type alba_backend: AlbaBackend
        :param abm_cluster_name: Name of the ABM cluster to add
        The code will claim the Arakoon clusters for this backend when provided
        :type abm_cluster_name: str
        :param requested_abm_cluster_name: The request ABM name for this backend
        :type requested_abm_cluster_name: str
        :param storagerouter: StorageRouter to install the ABM on
        :type storagerouter: StorageRouter
        :return:None
        :rtype: NoneType
        """
        # @todo revisit for external arakoons
        # Check if ABMs are available for claiming. When the requested cluster name is None, a different external ABM might be claimed
        metadata = ArakoonInstaller.get_unused_arakoon_metadata_and_claim(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.ABM,
                                                                          cluster_name=requested_abm_cluster_name)
        if metadata is None:  # No externally unused clusters found, we create 1 ourselves
            if not storagerouter:
                raise RuntimeError('No StorageRouter specified to install ABM on')
            if requested_abm_cluster_name is not None:
                raise ValueError('Cluster {0} has been claimed by another process'.format(requested_abm_cluster_name))
            self._logger.info('Creating Arakoon cluster: {0}'.format(abm_cluster_name))
            partition = self.get_db_partition(storagerouter)
            arakoon_installer = ArakoonInstaller(cluster_name=abm_cluster_name)
            arakoon_installer.create_cluster(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.ABM,
                                             ip=storagerouter.ip,
                                             base_dir=partition.folder,
                                             plugins={ABM_PLUGIN: self.version_str})
            ssh_client = self.get_ssh_client(storagerouter)
            self.link_plugins(client=ssh_client, data_dir=partition.folder, plugins=[ABM_PLUGIN], cluster_name=abm_cluster_name)
            arakoon_installer.start_cluster()
            ports = arakoon_installer.ports[storagerouter.ip]
            metadata = arakoon_installer.metadata
        else:
            ports = []
            storagerouter = None

        abm_cluster_name = metadata['cluster_name']
        cluster_manage_type = 'externally' if storagerouter is None else 'internally'
        self._logger.info('Claimed {0} managed Arakoon cluster: {1}'.format(cluster_manage_type, abm_cluster_name))
        ip = self.get_an_ip()
        self.update_abm_client_config(abm_cluster_name, ip=ip)
        self.model_arakoon_service(alba_backend, abm_cluster_name, ports, storagerouter)

    def extend_abm_cluster(self, storagerouter, abm_cluster, ssh_client=None):
        # type: (StorageRouter, ABMCluster, Optional[SSHClient]) -> None
        """
        Extend the ABM cluster to reach the desired safety
        :param storagerouter: StorageRouter to extend to
        :type storagerouter: StorageRouter
        :param abm_cluster: ABM Cluster object to extend
        :type abm_cluster: ABMCluster
        :param ssh_client: SSHClient to the StorageRouter
        :type ssh_client: SSHClient
        :return:None
        :rtype: NoneType
        """
        alba_backend = abm_cluster.alba_backend
        partition = self.get_db_partition(storagerouter)
        ssh_client = ssh_client or SSHClient(storagerouter)

        arakoon_installer = ArakoonInstaller(cluster_name=abm_cluster.name)
        arakoon_installer.load()
        arakoon_installer.extend_cluster(new_ip=storagerouter.ip, base_dir=partition.folder, plugins={ABM_PLUGIN: self.version_str})
        self.link_plugins(client=ssh_client, data_dir=partition.folder, plugins=[ABM_PLUGIN], cluster_name=abm_cluster.name)
        self.model_arakoon_service(alba_backend=alba_backend, cluster_name=abm_cluster.name,
                                   ports=arakoon_installer.ports[storagerouter.ip], storagerouter=storagerouter)
        arakoon_installer.restart_cluster_after_extending(new_ip=storagerouter.ip)
        self.update_abm_client_config(abm_name=abm_cluster.name, ip=storagerouter.ip)

    @classmethod
    def remove_abm_cluster(cls, abm_cluster, arakoon_clusters=None):
        # type: (ABMCluster, Optional[List[str]]) -> None
        """
        :param abm_cluster: ABM Cluster to remove
        :type abm_cluster: ABMCluster
        :param arakoon_clusters: All available arakoon clusters (Defaults to fetching them)
        :type arakoon_clusters: List[str]
        :return: None
        :rtype: NoneType
        """
        internal = cls.is_internally_managed(abm_cluster=abm_cluster)
        cls._remove_cluster(abm_cluster.name, internal, associated_junction_services=abm_cluster.abm_services,
                            junction_type=ABMService, arakoon_clusters=arakoon_clusters)
        # Remove item
        abm_cluster.delete()


class NSMInstaller(AlbaArakoonInstaller):

    def __init__(self, version_str=None, ssh_clients=None):
        # type: (Optional[str], Optional[Dict[StorageRouter, SSHClient]]) -> None
        """
        Initialize an AlbaArakoonInstaller
        :param ssh_clients: Dict with SSHClients for every Storagerouter
        This dict is consulted first before building an SSHClient in the code.
        Used to re-use already established connection and avoid failures on connecting to a storagerouter
        :type ssh_clients: Dict[StorageRouter, SSHClient]
        :param version_str: String of the Alba version to use
        :type version_str: str
        """
        super(NSMInstaller, self).__init__(version_str, ssh_clients)

    def deploy_nsm_cluster(self, alba_backend, storagerouter=None, nsm_cluster_name=None, nsm_clusters=None):
        # type: (AlbaBackend, Optional[StorageRouter], Optional[str], Optional[List[str]]) -> None
        """
        Deploy an NSM cluster.
        Will attempt to claim external NSMs if they are available
        :param alba_backend: Alba Backend to deploy the NSM cluster for
        :type alba_backend: str
        :param storagerouter: StorageRouter to deploy NSM on (internal)
        :type storagerouter: StorageRouter
        :param nsm_cluster_name: The name for the NSM cluster to be deployed
        :type nsm_cluster_name: str
        :param nsm_clusters: List with the names of the NSM clusters to claim for this backend
        :type nsm_clusters: List[str]
        :return:None
        :rtype: NoneType
        """
        # @todo revisit for external
        if nsm_clusters is None:
            nsm_clusters = []
        ports = []
        if len(nsm_clusters) > 0:
            # Check if the external NSMs can be used
            metadatas = []
            for external_nsm_cluster in nsm_clusters:
                # Claim the external nsm
                metadata = ArakoonInstaller.get_unused_arakoon_metadata_and_claim(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM,
                                                                                  cluster_name=external_nsm_cluster)
                if metadata is None:  # External NSM could not be claimed. Revert all others
                    self._logger.warning('Arakoon cluster {0} has been claimed by another process, reverting...'.format(external_nsm_cluster))
                    for md in metadatas:
                        ArakoonInstaller(cluster_name=md['cluster_name']).unclaim_cluster()
                    ArakoonInstaller(cluster_name=alba_backend.abm_cluster.name).unclaim_cluster()
                    raise ValueError('Arakoon cluster {0} has been claimed by another process'.format(external_nsm_cluster))
                metadatas.append(metadata)
        else:
            metadata = ArakoonInstaller.get_unused_arakoon_metadata_and_claim(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM)
            if metadata is None:  # No externally unused clusters found, we create 1 ourselves
                if not storagerouter:
                    raise RuntimeError('Could not find any partitions with DB role')
                partition = self.get_db_partition(storagerouter)
                nsm_cluster_name = nsm_cluster_name or '{0}-nsm_0'.format(alba_backend.name)
                self._logger.info('ALBA Backend {0} - Creating NSM cluster {1}'.format(alba_backend.name, nsm_cluster_name))
                arakoon_installer = ArakoonInstaller(cluster_name=nsm_cluster_name)
                arakoon_installer.create_cluster(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM,
                                                 ip=storagerouter.ip,
                                                 base_dir=partition.folder,
                                                 plugins={NSM_PLUGIN: self.version_str})
                ssh_client = self.get_ssh_client(storagerouter)
                self._logger.info('ALBA Backend {0} - Cluster {1} - Linking plugins'.format(alba_backend.name, nsm_cluster_name))
                self.link_plugins(client=ssh_client, data_dir=partition.folder, plugins=[NSM_PLUGIN], cluster_name=nsm_cluster_name)
                self._logger.info('ALBA Backend {0} - Cluster {1} - Starting cluster'.format(alba_backend.name, nsm_cluster_name))
                arakoon_installer.start_cluster()
                ports = arakoon_installer.ports[storagerouter.ip]
                metadata = arakoon_installer.metadata
            metadatas = [metadata]

        for index, metadata in enumerate(metadatas):
            nsm_cluster_name = metadata['cluster_name']
            cluster_manage_type = 'externally' if storagerouter is None else 'internally'
            self._logger.info('Claimed {0} managed Arakoon cluster: {1}'.format(cluster_manage_type, nsm_cluster_name))
            ip = self.get_an_ip()
            self._logger.debug('ALBA Backend {0} - Cluster {1} - Registering NSM'.format(alba_backend.name, nsm_cluster_name))
            self.register_nsm(abm_name=alba_backend.abm_cluster.name, nsm_name=nsm_cluster_name, ip=ip)
            self._logger.debug('ALBA Backend {0} - Cluster {1} - Modeling services'.format(alba_backend.name, nsm_cluster_name))
            self.model_arakoon_service(alba_backend=alba_backend, cluster_name=nsm_cluster_name, ports=ports,
                                       storagerouter=None if len(nsm_clusters) > 0 else storagerouter, number=index)

    def extend_nsm_cluster(self, storagerouter, nsm_cluster, ssh_client=None):
        # type: (StorageRouter, NSMCluster, Optional[SSHClient]) -> None
        """
        Extend the NSM cluster to another StorageRouter
        :return:None
        :rtype: NoneType
        """
        alba_backend = nsm_cluster.alba_backend
        ssh_client = ssh_client or SSHClient(storagerouter)
        partition = self.get_db_partition(storagerouter)
        arakoon_installer = ArakoonInstaller(cluster_name=nsm_cluster.name)
        arakoon_installer.load()

        self._logger.debug('ALBA Backend {0} - Extending cluster {1} on node {2} with IP {3}'.format(alba_backend.name, nsm_cluster.name, storagerouter.name, storagerouter.ip))
        arakoon_installer.extend_cluster(new_ip=storagerouter.ip, base_dir=partition.folder, plugins={NSM_PLUGIN: self.version_str})
        self._logger.debug('ALBA Backend {0} - Linking plugins'.format(alba_backend.name))
        self.link_plugins(client=ssh_client, data_dir=partition.folder, plugins=[NSM_PLUGIN], cluster_name=nsm_cluster.name)
        self._logger.debug('ALBA Backend {0} - Modeling services'.format(alba_backend.name))
        self.model_arakoon_service(alba_backend=alba_backend, cluster_name=nsm_cluster.name,
                                   ports=arakoon_installer.ports[storagerouter.ip], storagerouter=storagerouter,
                                   number=nsm_cluster.number)
        self._logger.debug('ALBA Backend {0} - Restarting cluster'.format(alba_backend.name))
        arakoon_installer.restart_cluster_after_extending(new_ip=storagerouter.ip)
        self.update_nsm(abm_name=alba_backend.abm_cluster.name, nsm_name=nsm_cluster.name, ip=storagerouter.ip)
        self._logger.debug('ALBA Backend {0} - Extended cluster'.format(alba_backend.name))

    @classmethod
    def register_nsm(cls, abm_name, nsm_name, ip):
        # type: (str, str, str) -> None
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
        AlbaCLI.run(command='add-nsm-host', config=abm_config_file, extra_params=[nsm_config_file], client=SSHClient(endpoint=ip))

    @classmethod
    def update_nsm(cls, abm_name, nsm_name, ip):
        # type: (str, str, str) -> None
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

    @classmethod
    def remove_nsm_cluster(cls, nsm_cluster, arakoon_clusters=None):
        # type: (NSMCluster, Optional[List[str]]) -> None
        """
        :param nsm_cluster: NSM Cluster to remove
        :type nsm_cluster: NSMCluster
        :param arakoon_clusters: All available arakoon clusters (Defaults to fetching them)
        :type arakoon_clusters: List[str]
        :return: None
        :rtype: NoneType
        """
        internal = cls.is_internally_managed(nsm_cluster=nsm_cluster)
        cls._remove_cluster(nsm_cluster.name, internal,
                            associated_junction_services=nsm_cluster.nsm_services,
                            junction_type=NSMService, arakoon_clusters=arakoon_clusters)
        # Remove item
        nsm_cluster.delete()


class S3TransactionInstaller(AlbaArakoonInstaller):
    """
    Managed the S3 Transaction Arakoon cluster
    """

    def __init__(self, version_str=None, ssh_clients=None):
        # type: (Optional[str], Optional[Dict[StorageRouter, SSHClient]]) -> None
        """
        Initialize an AlbaArakoonInstaller
        :param ssh_clients: Dict with SSHClients for every Storagerouter
        This dict is consulted first before building an SSHClient in the code.
        Used to re-use already established connection and avoid failures on connecting to a storagerouter
        :type ssh_clients: Dict[StorageRouter, SSHClient]
        :param version_str: String of the Alba version to use
        :type version_str: str
        """
        super(S3TransactionInstaller, self).__init__(version_str, ssh_clients)

    def deploy_s3_cluster(self, storagerouter=None, cluster_name='alba_s3_transaction', external_cluster_name=None):
        # type: (Optional[StorageRouter], Optional[str], Optional[str]) -> None
        """
        Deploy a S3 Arakoon cluster
        :param storagerouter: StorageRouter to deploy NSM on (internal)
        :type storagerouter: StorageRouter
        :param cluster_name: The name for the cluster to be deployed. Defaults to `alba_s3_transaction`
        :type cluster_name: str
        :param external_cluster_name: Name of the external cluster to claim
        :type external_cluster_name: str
        :return: None
        :rtype: NoneType
        """
        # @todo create a generic method to share with ABM
        # Check if ABMs are available for claiming. When the requested cluster name is None, a different external ABM might be claimed
        metadata = ArakoonInstaller.get_unused_arakoon_metadata_and_claim(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.ABM,
                                                                          cluster_name=external_cluster_name)
        if metadata is None:  # No externally unused clusters found, we create 1 ourselves
            if not storagerouter:
                raise RuntimeError('No StorageRouter specified to install cluster on')
            if external_cluster_name is not None:
                raise ValueError('Cluster {0} has been claimed by another process'.format(external_cluster_name))
            self._logger.info('Creating Arakoon cluster: {0}'.format(cluster_name))
            partition = self.get_db_partition(storagerouter)
            arakoon_installer = ArakoonInstaller(cluster_name=cluster_name)
            arakoon_installer.create_cluster(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.ABM,
                                             ip=storagerouter.ip,
                                             base_dir=partition.folder)
            ssh_client = self.get_ssh_client(storagerouter)
            self.link_plugins(client=ssh_client, data_dir=partition.folder, plugins=[ABM_PLUGIN], cluster_name=cluster_name)
            arakoon_installer.start_cluster()
            ports = arakoon_installer.ports[storagerouter.ip]
            metadata = arakoon_installer.metadata
        else:
            ports = []
            storagerouter = None

        cluster_name = metadata['cluster_name']
        cluster_manage_type = 'externally' if storagerouter is None else 'internally'
        self._logger.info('Claimed {0} managed Arakoon cluster: {1}'.format(cluster_manage_type, cluster_name))
        self.model_s3_arakoon_service(cluster_name, ports, storagerouter)

    def extend_s3_cluster(self, storagerouter, s3_cluster):
        # type: (StorageRouter, S3TransactionCluster) -> None
        """
        Extend the ABM cluster to reach the desired safety
        :param storagerouter: StorageRouter to extend to
        :type storagerouter: StorageRouter
        :param s3_cluster: S3 cluster object to extend
        :type s3_cluster: S3 cluster
        :return:None
        :rtype: NoneType
        """
        partition = self.get_db_partition(storagerouter)

        arakoon_installer = ArakoonInstaller(cluster_name=s3_cluster.name)
        arakoon_installer.load()
        arakoon_installer.extend_cluster(new_ip=storagerouter.ip, base_dir=partition.folder)
        self.model_s3_arakoon_service(cluster_name=s3_cluster.name, ports=arakoon_installer.ports[storagerouter.ip], storagerouter=storagerouter)
        arakoon_installer.restart_cluster_after_extending(new_ip=storagerouter.ip)

    @classmethod
    def remove_s3_cluster(cls, s3_cluster, arakoon_clusters=None):
        # type: (S3TransactionCluster, Optional[List[str]]) -> None
        """
        :param s3_cluster: S3 Transaction Cluster to remove
        :type s3_cluster: S3TransactionCluster
        :param arakoon_clusters: All available arakoon clusters (Defaults to fetching them)
        :type arakoon_clusters: List[str]
        :return: None
        :rtype: NoneType
        """
        internal = cls.is_internally_managed(s3_cluster=s3_cluster)
        cls._remove_cluster(s3_cluster.name, internal,
                            associated_junction_services=s3_cluster.s3_transaction_services,
                            junction_type=NSMService, arakoon_clusters=arakoon_clusters)
        # Remove item
        s3_cluster.delete()

    @classmethod
    def model_s3_arakoon_service(cls, cluster_name, ports=None, storagerouter=None):
        # type: (str, Optional[List[int]], Optional[StorageRouter]) -> None
        """
        Adds S3 service to the model
        :param cluster_name: Name of the cluster the service belongs to
        :type cluster_name: str
        :param ports: Ports on which the service is listening (None if externally managed service)
        :type ports: list
        :param storagerouter: StorageRouter on which the service has been deployed (None if externally managed service)
        :type storagerouter: ovs.dal.hybrids.storagerouter.StorageRouter
        :return: None
        :rtype: NoneType
        """
        if ports is None:
            ports = []

        service_type = ServiceTypeList.get_by_name(ServiceType.SERVICE_TYPES.ALBA_S3_TRANSACTION)
        cluster = S3TransactionClusterList.get_by_name(cluster_name) or S3TransactionCluster()
        service_name = 'arakoon_s3_transaction'
        junction_service = S3TransactionService()

        cls._logger.info('Model service: {0}'.format(str(service_name)))
        cluster.name = cluster_name
        cluster.config_location = ArakoonClusterConfig.CONFIG_KEY.format(cluster_name)
        cluster.save()

        service = DalService()
        service.name = service_name
        service.type = service_type
        service.ports = ports
        service.storagerouter = storagerouter
        service.save()

        junction_service.s3_transaction_cluster = cluster
        junction_service.service = service
        junction_service.save()
