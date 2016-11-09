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
Module for UpdateController
"""
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs.extensions.packages.package import PackageManager
from ovs.lib.helpers.decorators import add_hooks
from ovs.log.log_handler import LogHandler


class UpdateController(object):
    """
    This class contains all logic for updating an environment
    """
    _logger = LogHandler.get('lib', name='update-alba-plugin')
    _logger.logger.propagate = False

    @staticmethod
    @add_hooks('update', 'package_info')
    def get_package_information(client, package_info):
        """
        Retrieve and store the package information for the StorageRouter represented by the client provided
        :param client: Client on which to collect package information
        :type client: SSHClient
        :param package_info: Dictionary passed in by the thread calling this function
        :type package_info: dict
        :return: Package information
        :rtype: dict
        """
        relevant_packages = ['alba', 'arakoon', 'openvstorage-backend-core', 'openvstorage-backend-webapps', 'openvstorage-sdm', 'volumedriver-no-dedup-base', 'volumedriver-no-dedup-server']
        installed = PackageManager.get_installed_versions(client=client, package_names=relevant_packages)
        candidate = PackageManager.get_candidate_versions(client=client, package_names=relevant_packages)
        if set(installed.keys()) != set(relevant_packages) or set(candidate.keys()) != set(relevant_packages):
            raise RuntimeError('Failed to retrieve the installed and candidate versions for packages: {0}'.format(', '.join(relevant_packages)))

        for component, package_names in {'framework': ['openvstorage-backend-core', 'openvstorage-backend-webapps'],
                                         'alba-plugin': ['alba', 'arakoon', 'openvstorage-sdm'],
                                         'storagedriver': ['alba', 'arakoon', 'volumedriver-no-dedup-base', 'volumedriver-no-dedup-server']}.iteritems():
            if component != 'alba-plugin':  # Framework, storagedriver can potentially be updated in other hooks too
                package_info[client.ip][component].update(dict((package_name, {'installed': installed[package_name], 'candidate': candidate[package_name]}) for package_name in package_names))
            else:
                package_info[client.ip].update({component: dict((package_name, {'installed': installed[package_name], 'candidate': candidate[package_name]}) for package_name in package_names)})

    # @staticmethod
    # @add_hooks('update', 'metadata')
    # def get_metadata_sdm(client):
    #     """
    #     Retrieve information about the SDM packages
    #     :param client: SSHClient on which to retrieve the metadata
    #     :type client: SSHClient
    #     :return: Information about services to restart,
    #                                packages to update,
    #                                information about potential downtime
    #                                information about unmet prerequisites
    #     :rtype: dict
    #     """
    #     other_storage_router_ips = [sr.ip for sr in StorageRouterList.get_storagerouters() if sr.ip != client.ip]
    #     version = ''
    #     for node in AlbaNodeList.get_albanodes():
    #         if node.ip in other_storage_router_ips:
    #             continue
    #         try:
    #             candidate = node.client.get_update_information()
    #             if candidate.get('version'):
    #                 version = candidate['version']
    #                 break
    #         except ValueError as ve:
    #             if 'No JSON object could be decoded' in ve.message:
    #                 version = 'Remote ASD'
    #     return {'framework': [{'name': 'openvstorage-sdm',
    #                            'version': version,
    #                            'services': [],
    #                            'packages': [],
    #                            'downtime': [],
    #                            'namespace': 'alba',
    #                            'prerequisites': []}]}
    #
    # @staticmethod
    # @add_hooks('update', 'metadata')
    # def get_metadata_alba(client):
    #     """
    #     Retrieve ALBA packages and services which ALBA depends upon
    #     Also check the arakoon clusters to be able to warn the customer for potential downtime
    #     :param client: SSHClient on which to retrieve the metadata
    #     :type client: SSHClient
    #     :return: Information about services to restart,
    #                                packages to update,
    #                                information about potential downtime
    #                                information about unmet prerequisites
    #     :rtype: dict
    #     """
    #     downtime = []
    #     alba_services = set()
    #     arakoon_cluster_services = set()
    #     for albabackend in AlbaBackendList.get_albabackends():
    #         alba_services.add('{0}_{1}'.format(AlbaController.ALBA_MAINTENANCE_SERVICE_PREFIX, albabackend.backend.name))
    #         arakoon_cluster_services.add('arakoon-{0}'.format(albabackend.abm_services[0].service.name))
    #         arakoon_cluster_services.update(['arakoon-{0}'.format(service.service.name) for service in albabackend.nsm_services])
    #         if len(albabackend.abm_services) < 3:
    #             downtime.append(('alba', 'backend', albabackend.backend.name))
    #             continue  # No need to check other services for this backend since downtime is a fact
    #
    #         nsm_service_info = {}
    #         for service in albabackend.nsm_services:
    #             if service.service.name not in nsm_service_info:
    #                 nsm_service_info[service.service.name] = 0
    #             nsm_service_info[service.service.name] += 1
    #         if min(nsm_service_info.values()) < 3:
    #             downtime.append(('alba', 'backend', albabackend.backend.name))
    #
    #     core_info = PackageManager.verify_update_required(packages=['openvstorage-backend-core', 'openvstorage-backend-webapps'],
    #                                                       services=['watcher-framework', 'memcached'],
    #                                                       client=client)
    #     alba_info = PackageManager.verify_update_required(packages=['alba'],
    #                                                       services=list(alba_services),
    #                                                       client=client)
    #     arakoon_info = PackageManager.verify_update_required(packages=['arakoon'],
    #                                                          services=list(arakoon_cluster_services),
    #                                                          client=client)
    #
    #     return {'framework': [{'name': 'openvstorage-backend',
    #                            'version': core_info['version'],
    #                            'services': core_info['services'],
    #                            'packages': core_info['packages'],
    #                            'downtime': [],
    #                            'namespace': 'alba',
    #                            'prerequisites': []},
    #                           {'name': 'alba',
    #                            'version': alba_info['version'],
    #                            'services': alba_info['services'],
    #                            'packages': alba_info['packages'],
    #                            'downtime': downtime,
    #                            'namespace': 'alba',
    #                            'prerequisites': []},
    #                           {'name': 'arakoon',
    #                            'version': arakoon_info['version'],
    #                            'services': [],
    #                            'packages': arakoon_info['packages'],
    #                            'downtime': downtime,
    #                            'namespace': 'alba',
    #                            'prerequisites': []}]}
    #
    # @staticmethod
    # @add_hooks('update', 'postupgrade')
    # def upgrade_sdm(client):
    #     """
    #     Upgrade the openvstorage-sdm packages
    #     :param client: SSHClient to 1 of the master nodes (On which the update is initiated)
    #     :type client: SSHClient
    #     :return: None
    #     """
    #     storagerouter_ips = [sr.ip for sr in StorageRouterList.get_storagerouters()]
    #     other_storagerouter_ips = [ip for ip in storagerouter_ips if ip != client.ip]
    #
    #     nodes_to_upgrade = []
    #     all_nodes_to_upgrade = []
    #     for node in AlbaNodeList.get_albanodes():
    #         version_info = node.client.get_update_information()
    #         # Some odd information we get back here, but we don't change it because backwards compatibility
    #         # Pending updates: SDM  ASD
    #         #                   Y    Y    -> installed = 1.0, version = 1.1
    #         #                   Y    N    -> installed = 1.0, version = 1.1
    #         #                   N    Y    -> installed = 1.0, version = 1.0  (They are equal, but there's an ASD update pending)
    #         #                   N    N    -> installed = 1.0, version =      (No version? This means there's no update)
    #         pending = version_info['version']
    #         installed = version_info['installed']
    #         if pending != '':  # If there is any update (SDM or ASD)
    #             if pending.startswith('1.6.') and installed.startswith('1.5.'):
    #                 # 2.6 to 2.7 upgrade
    #                 if node.ip not in storagerouter_ips:
    #                     AlbaController._logger.warning('A non-hyperconverged node with pending upgrade from 2.6 (1.5) to 2.7 (1.6) was detected. No upgrade possible')
    #                     return
    #             all_nodes_to_upgrade.append(node)
    #             if node.ip not in other_storagerouter_ips:
    #                 nodes_to_upgrade.append(node)
    #
    #     for node in nodes_to_upgrade:
    #         AlbaController._logger.info('{0}: Upgrading SDM'.format(node.ip))
    #         counter = 0
    #         max_counter = 12
    #         status = 'started'
    #         while True and counter < max_counter:
    #             counter += 1
    #             try:
    #                 status = node.client.execute_update(status).get('status')
    #                 if status == 'done':
    #                     break
    #             except Exception as ex:
    #                 AlbaController._logger.warning('Attempt {0} to update SDM failed, trying again'.format(counter))
    #                 if counter == max_counter:
    #                     AlbaController._logger.error('{0}: Error during update: {1}'.format(node.ip, ex.message))
    #                 time.sleep(10)
    #         if status != 'done':
    #             AlbaController._logger.error('{0}: Failed to perform SDM update. Please check the appropriate logfile on the node'.format(node.ip))
    #             raise Exception('Status after upgrade is "{0}"'.format(status))
    #         node.client.restart_services()
    #         all_nodes_to_upgrade.remove(node)
    #
    #     for alba_backend in AlbaBackendList.get_albabackends():
    #         service_name = '{0}_{1}'.format(AlbaController.ALBA_MAINTENANCE_SERVICE_PREFIX, alba_backend.backend.name)
    #         if ServiceManager.has_service(service_name, client=client) is True:
    #             if ServiceManager.get_service_status(service_name, client=client)[0] is True:
    #                 ServiceManager.stop_service(service_name, client=client)
    #             ServiceManager.remove_service(service_name, client=client)
    #
    #     AlbaController.checkup_maintenance_agents.delay()
    #
    # @staticmethod
    # @add_hooks('update', 'postupgrade')
    # def restart_arakoon_clusters(client):
    #     """
    #     Restart all arakoon clusters after arakoon and/or alba package upgrade
    #     :param client: SSHClient to 1 of the master nodes (On which the update is initiated)
    #     :type client: SSHClient
    #     :return: None
    #     """
    #     services = []
    #     for alba_backend in AlbaBackendList.get_albabackends():
    #         services.append('arakoon-{0}'.format(alba_backend.abm_services[0].service.name))
    #         services.extend(list(set(['arakoon-{0}'.format(service.service.name) for service in alba_backend.nsm_services])))
    #
    #     info = PackageManager.verify_update_required(packages=['arakoon'],
    #                                                  services=services,
    #                                                  client=client)
    #     for service in info['services']:
    #         cluster_name = service.lstrip('arakoon-')
    #         AlbaController._logger.info('Restarting cluster {0}'.format(cluster_name), print_msg=True)
    #         ArakoonInstaller.restart_cluster(cluster_name=cluster_name,
    #                                          master_ip=client.ip,
    #                                          filesystem=False)
    #     else:  # In case no arakoon clusters are restarted, we check if alba has been updated and still restart clusters
    #         proxies = []
    #         this_sr = StorageRouterList.get_by_ip(client.ip)
    #         for sr in StorageRouterList.get_storagerouters():
    #             for service in sr.services:
    #                 if service.type.name == ServiceType.SERVICE_TYPES.ALBA_PROXY and service.storagerouter_guid == this_sr.guid:
    #                     proxies.append(service.name)
    #         if proxies:
    #             info = PackageManager.verify_update_required(packages=['alba'],
    #                                                          services=proxies,
    #                                                          client=client)
    #             if info['services']:
    #                 for service in services:
    #                     cluster_name = service.lstrip('arakoon-')
    #                     AlbaController._logger.info('Restarting cluster {0} because of ALBA update'.format(cluster_name), print_msg=True)
    #                     ArakoonInstaller.restart_cluster(cluster_name=cluster_name,
    #                                                      master_ip=client.ip,
    #                                                      filesystem=False)
    #
    # @staticmethod
    # @add_hooks('update', 'postupgrade')
    # def upgrade_alba_plugin(client):
    #     """
    #     Upgrade the ALBA plugin
    #     :param client: SSHClient to connect to for upgrade
    #     :type client: SSHClient
    #     :return: None
    #     """
    #     from ovs.dal.lists.albabackendlist import AlbaBackendList
    #     alba_backends = AlbaBackendList.get_albabackends()
    #     for alba_backend in alba_backends:
    #         alba_backend_name = alba_backend.backend.name
    #         service_name = '{0}_{1}'.format(AlbaController.ALBA_REBALANCER_SERVICE_PREFIX, alba_backend_name)
    #         if ServiceManager.has_service(service_name, client=client) is True:
    #             if ServiceManager.get_service_status(service_name, client=client)[0] is True:
    #                 ServiceManager.stop_service(service_name, client=client)
    #             ServiceManager.remove_service(service_name, client=client)
