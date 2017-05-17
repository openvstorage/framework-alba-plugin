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
ALBA migration module
"""

from ovs.dal.hybrids.backendtype import BackendType
from ovs.dal.lists.backendtypelist import BackendTypeList


class ALBAMigrator(object):
    """
    Handles all model related migrations
    """

    identifier = 'alba'
    THIS_VERSION = 14

    def __init__(self):
        """ Init method """
        pass

    @staticmethod
    def migrate(previous_version):
        """
        Migrates from a given version to the current version. It uses 'previous_version' to be smart
        wherever possible, but the code should be able to migrate any version towards the expected version.
        When this is not possible, the code can set a minimum version and raise when it is not met.
        :param previous_version: The previous version from which to start the migration
        :type previous_version: float
        """

        working_version = previous_version

        if working_version == 0:
            from ovs.dal.hybrids.servicetype import ServiceType
            # Initial version:
            # * Add any basic configuration or model entries

            # Add backends
            for backend_type_info in [('ALBA', 'alba')]:
                code = backend_type_info[1]
                backend_type = BackendTypeList.get_backend_type_by_code(code)
                if backend_type is None:
                    backend_type = BackendType()
                backend_type.name = backend_type_info[0]
                backend_type.code = code
                backend_type.save()

            # Add service types
            for service_type_info in [ServiceType.SERVICE_TYPES.NS_MGR, ServiceType.SERVICE_TYPES.ALBA_MGR]:
                service_type = ServiceType()
                service_type.name = service_type_info
                service_type.save()

        # From here on, all actual migration should happen to get to the expected state for THIS RELEASE
        elif working_version < ALBAMigrator.THIS_VERSION:
            import hashlib
            from ovs.dal.helpers import HybridRunner, Descriptor
            from ovs.dal.hybrids.albaabmcluster import ABMCluster
            from ovs.dal.hybrids.albansmcluster import NSMCluster
            from ovs.dal.hybrids.j_abmservice import ABMService
            from ovs.dal.hybrids.j_nsmservice import NSMService
            from ovs.dal.hybrids.service import Service
            from ovs.dal.hybrids.servicetype import ServiceType
            from ovs.dal.lists.albabackendlist import AlbaBackendList
            from ovs.dal.lists.servicetypelist import ServiceTypeList
            from ovs.dal.lists.storagerouterlist import StorageRouterList
            from ovs_extensions.db.arakoon.ArakoonInstaller import ArakoonClusterConfig, ArakoonInstaller
            from ovs.extensions.generic.configuration import Configuration, NotFoundException
            from ovs_extensions.generic.toolbox import ExtensionsToolbox
            from ovs.extensions.plugins.albacli import AlbaCLI
            from ovs_extensions.storage.persistentfactory import PersistentFactory

            # Migrate unique constraints & indexes
            client = PersistentFactory.get_client()
            hybrid_structure = HybridRunner.get_hybrids()
            for class_descriptor in hybrid_structure.values():
                cls = Descriptor().load(class_descriptor).get_object()
                classname = cls.__name__.lower()
                unique_key = 'ovs_unique_{0}_{{0}}_'.format(classname)
                index_prefix = 'ovs_index_{0}|{{0}}|'.format(classname)
                index_key = 'ovs_index_{0}|{{0}}|{{1}}'.format(classname)
                uniques = []
                indexes = []
                # noinspection PyProtectedMember
                for prop in cls._properties:
                    if prop.unique is True and len([k for k in client.prefix(unique_key.format(prop.name))]) == 0:
                        uniques.append(prop.name)
                    if prop.indexed is True and len([k for k in client.prefix(index_prefix.format(prop.name))]) == 0:
                        indexes.append(prop.name)
                if len(uniques) > 0 or len(indexes) > 0:
                    prefix = 'ovs_data_{0}_'.format(classname)
                    for key, data in client.prefix_entries(prefix):
                        for property_name in uniques:
                            ukey = '{0}{1}'.format(unique_key.format(property_name), hashlib.sha1(str(data[property_name])).hexdigest())
                            client.set(ukey, key)
                        for property_name in indexes:
                            if property_name not in data:
                                continue  # This is the case when there's a new indexed property added.
                            ikey = index_key.format(property_name, hashlib.sha1(str(data[property_name])).hexdigest())
                            index = list(client.get_multi([ikey], must_exist=False))[0]
                            transaction = client.begin_transaction()
                            if index is None:
                                client.assert_value(ikey, None, transaction=transaction)
                                client.set(ikey, [key], transaction=transaction)
                            elif key not in index:
                                client.assert_value(ikey, index[:], transaction=transaction)
                                client.set(ikey, index + [key], transaction=transaction)
                            client.apply_transaction(transaction)

            #############################################
            # Introduction of ABMCluster and NSMCluster #
            #############################################
            # Verify presence of unchanged ALBA Backends
            alba_backends = AlbaBackendList.get_albabackends()
            changes_required = False
            for alba_backend in alba_backends:
                if alba_backend.abm_cluster is None or len(alba_backend.nsm_clusters) == 0:
                    changes_required = True
                    break

            if changes_required:
                # Retrieve ABM and NSM clusters
                abm_cluster_info = []
                nsm_cluster_info = []
                for cluster_name in Configuration.list('/ovs/arakoon'):
                    try:
                        metadata = ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=cluster_name)
                        if metadata['cluster_type'] == ServiceType.ARAKOON_CLUSTER_TYPES.ABM:
                            abm_cluster_info.append(metadata)
                        elif metadata['cluster_type'] == ServiceType.ARAKOON_CLUSTER_TYPES.NSM:
                            nsm_cluster_info.append(metadata)
                    except NotFoundException:
                        continue

                # Retrieve NSM Arakoon cluster information
                cluster_arakoon_map = {}
                for cluster_info in abm_cluster_info + nsm_cluster_info:
                    cluster_name = cluster_info['cluster_name']
                    arakoon_config = ArakoonClusterConfig(cluster_id=cluster_name)
                    cluster_arakoon_map[cluster_name] = arakoon_config.export()

                storagerouter_map = dict((storagerouter.machine_id, storagerouter) for storagerouter in StorageRouterList.get_storagerouters())
                alba_backend_id_map = dict((alba_backend.alba_id, alba_backend) for alba_backend in alba_backends)
                for cluster_info in abm_cluster_info:
                    internal = cluster_info['internal']
                    cluster_name = cluster_info['cluster_name']
                    config_location = Configuration.get_configuration_path(key=ArakoonClusterConfig.CONFIG_KEY.format(cluster_name))
                    try:
                        alba_id = AlbaCLI.run(command='get-alba-id', config=config_location, named_params={'attempts': 3})['id']
                        nsm_hosts = AlbaCLI.run(command='list-nsm-hosts', config=config_location, named_params={'attempts': 3})
                    except RuntimeError:
                        continue

                    alba_backend = alba_backend_id_map.get(alba_id)
                    if alba_backend is None:  # ALBA Backend with ID not found in model
                        continue
                    if alba_backend.abm_cluster is not None and len(alba_backend.nsm_clusters) > 0:  # Clusters already exist
                        continue

                    # Create ABM Cluster
                    if alba_backend.abm_cluster is None:
                        abm_cluster = ABMCluster()
                        abm_cluster.name = cluster_name
                        abm_cluster.alba_backend = alba_backend
                        abm_cluster.config_location = ArakoonClusterConfig.CONFIG_KEY.format(cluster_name)
                        abm_cluster.save()
                    else:
                        abm_cluster = alba_backend.abm_cluster

                    # Create ABM Services
                    abm_arakoon_config = cluster_arakoon_map[cluster_name]
                    abm_arakoon_config.pop('global')
                    arakoon_nodes = abm_arakoon_config.keys()
                    if internal is False:
                        services_to_create = 1
                    else:
                        if set(arakoon_nodes).difference(set(storagerouter_map.keys())):
                            continue
                        services_to_create = len(arakoon_nodes)
                    for index in range(services_to_create):
                        service = Service()
                        service.name = 'arakoon-{0}-abm'.format(alba_backend.name)
                        service.type = ServiceTypeList.get_by_name(ServiceType.SERVICE_TYPES.ALBA_MGR)
                        if internal is True:
                            arakoon_node_config = abm_arakoon_config[arakoon_nodes[index]]
                            service.ports = [arakoon_node_config['client_port'], arakoon_node_config['messaging_port']]
                            service.storagerouter = storagerouter_map[arakoon_nodes[index]]
                        else:
                            service.ports = []
                            service.storagerouter = None
                        service.save()

                        abm_service = ABMService()
                        abm_service.service = service
                        abm_service.abm_cluster = abm_cluster
                        abm_service.save()

                    # Create NSM Clusters
                    for cluster_index, nsm_host in enumerate(sorted(nsm_hosts, key=lambda host: ExtensionsToolbox.advanced_sort(host['cluster_id'], '_'))):
                        nsm_cluster_name = nsm_host['cluster_id']
                        nsm_arakoon_config = cluster_arakoon_map.get(nsm_cluster_name)
                        if nsm_arakoon_config is None:
                            continue

                        number = cluster_index if internal is False else int(nsm_cluster_name.split('_')[-1])
                        nsm_cluster = NSMCluster()
                        nsm_cluster.name = nsm_cluster_name
                        nsm_cluster.number = number
                        nsm_cluster.alba_backend = alba_backend
                        nsm_cluster.config_location = ArakoonClusterConfig.CONFIG_KEY.format(nsm_cluster_name)
                        nsm_cluster.save()

                        # Create NSM Services
                        nsm_arakoon_config.pop('global')
                        arakoon_nodes = nsm_arakoon_config.keys()
                        if internal is False:
                            services_to_create = 1
                        else:
                            if set(arakoon_nodes).difference(set(storagerouter_map.keys())):
                                continue
                            services_to_create = len(arakoon_nodes)
                        for service_index in range(services_to_create):
                            service = Service()
                            service.name = 'arakoon-{0}-nsm_{1}'.format(alba_backend.name, number)
                            service.type = ServiceTypeList.get_by_name(ServiceType.SERVICE_TYPES.NS_MGR)
                            if internal is True:
                                arakoon_node_config = nsm_arakoon_config[arakoon_nodes[service_index]]
                                service.ports = [arakoon_node_config['client_port'], arakoon_node_config['messaging_port']]
                                service.storagerouter = storagerouter_map[arakoon_nodes[service_index]]
                            else:
                                service.ports = []
                                service.storagerouter = None
                            service.save()

                            nsm_service = NSMService()
                            nsm_service.service = service
                            nsm_service.nsm_cluster = nsm_cluster
                            nsm_service.save()

            # Clean up all junction services no longer linked to an ALBA Backend
            all_nsm_services = [service.nsm_service for service in ServiceTypeList.get_by_name(ServiceType.SERVICE_TYPES.NS_MGR).services if service.nsm_service.nsm_cluster is None]
            all_abm_services = [service.abm_service for service in ServiceTypeList.get_by_name(ServiceType.SERVICE_TYPES.ALBA_MGR).services if service.abm_service.abm_cluster is None]
            for abm_service in all_abm_services:
                abm_service.delete()
                abm_service.service.delete()
            for nsm_service in all_nsm_services:
                nsm_service.delete()
                nsm_service.service.delete()

        return ALBAMigrator.THIS_VERSION
