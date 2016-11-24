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
Module for AlbaUpdateController
"""
import requests
from ovs.dal.hybrids.servicetype import ServiceType
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs.extensions.db.arakoon.ArakoonInstaller import ArakoonClusterConfig, ArakoonInstaller
from ovs.extensions.generic.configuration import Configuration
from ovs.extensions.generic.sshclient import SSHClient, UnableToConnectException
from ovs.extensions.generic.toolbox import Toolbox
from ovs.extensions.packages.package import PackageManager
from ovs.lib.albacontroller import AlbaController
from ovs.lib.helpers.decorators import add_hooks
from ovs.lib.update import UpdateController
from ovs.log.log_handler import LogHandler


class AlbaUpdateController(object):
    """
    This class contains all logic for updating an environment
    """
    _logger = LogHandler.get('lib', name='update-alba-plugin')
    _logger.logger.propagate = False
    sdm_packages = {'alba', 'openvstorage-sdm'}
    alba_plugin_packages = {'alba', 'arakoon', 'openvstorage-backend'}
    all_alba_plugin_packages = sdm_packages.union(alba_plugin_packages)

    #########
    # HOOKS #
    #########
    @staticmethod
    @add_hooks('update', 'get_package_info_multi')
    def get_package_information_alba_plugin_storage_routers(client, package_info):
        """
        Retrieve information about the currently installed versions of the core packages
        Retrieve information about the versions to which each package can potentially be upgraded
        If installed version is different from candidate version --> store this information in model

        Additionally if installed version is identical to candidate version, check the services with a 'run' file
        Verify whether the running version is identical to the candidate version
        If different --> store this information in the model

        Result: Every package with updates or which requires services to be restarted is stored in the model

        :param client: Client on which to collect the version information
        :type client: SSHClient
        :param package_info: Dictionary passed in by the thread calling this function
        :type package_info: dict
        :return: Package information
        :rtype: dict
        """
        try:
            if client.username != 'root':
                raise RuntimeError('Only the "root" user can retrieve the package information')

            installed = PackageManager.get_installed_versions(client=client, package_names=AlbaUpdateController.all_alba_plugin_packages)
            candidate = PackageManager.get_candidate_versions(client=client, package_names=AlbaUpdateController.all_alba_plugin_packages)
            if set(installed.keys()) != set(AlbaUpdateController.all_alba_plugin_packages) or set(candidate.keys()) != set(AlbaUpdateController.all_alba_plugin_packages):
                raise RuntimeError('Failed to retrieve the installed and candidate versions for packages: {0}'.format(', '.join(AlbaUpdateController.all_alba_plugin_packages)))

            storagerouter = StorageRouterList.get_by_ip(client.ip)
            arakoon_services = []
            for service in storagerouter.services:
                if service.type.name == ServiceType.SERVICE_TYPES.ALBA_MGR or service.type.name == ServiceType.SERVICE_TYPES.NS_MGR:
                    arakoon_services.append('arakoon-{0}'.format(service.name))

            for component, info in {'framework': {'arakoon': ['arakoon-ovsdb'],
                                                  'openvstorage-backend': []},
                                    'alba': {'alba': arakoon_services,
                                             'arakoon': arakoon_services}}.iteritems():
                packages = []
                for package_name, services in info.iteritems():
                    old = installed[package_name]
                    new = candidate[package_name]
                    if old != new:
                        packages.append({'name': package_name,
                                         'installed': old,
                                         'candidate': new,
                                         'namespace': 'alba',  # Namespace refers to json translation file: alba.json
                                         'services_to_restart': []})
                    else:
                        if package_name == 'arakoon':
                            services_to_restart = UpdateController.get_running_service_info(client=client,
                                                                                            services=dict((service_name, new) for service_name in services))
                        else:
                            services_to_restart = UpdateController.get_running_service_info(client=client,
                                                                                            services=dict((service_name, new) for service_name in services),
                                                                                            component='asd-manager')

                        if len(services_to_restart) > 0:
                            packages.append({'name': package_name,
                                             'installed': old,
                                             'candidate': new,
                                             'namespace': 'alba',
                                             'services_to_restart': services_to_restart})
                if component != 'alba':  # Framework, storagedriver can potentially be updated in other hooks too
                    package_info[client.ip][component].extend(packages)
                else:
                    package_info[client.ip][component] = packages
        except Exception as ex:
            if 'errors' not in package_info[client.ip]:
                package_info[client.ip]['errors'] = []
            package_info[client.ip]['errors'].append(ex)
        return package_info

    @staticmethod
    @add_hooks('update', 'get_package_info_single')
    def get_package_information_alba_plugin_storage_nodes(information):
        """
        Retrieve and store the package information for all AlbaNodes
        :return: None
        """
        for alba_node in AlbaNodeList.get_albanodes():
            if alba_node.ip not in information:
                information[alba_node.ip] = {'errors': []}
            elif 'errors' not in information[alba_node.ip]:
                information[alba_node.ip]['errors'] = []

            package_info = {}
            try:
                package_info = alba_node.client.get_update_information()
            except (requests.ConnectionError, requests.Timeout):
                AlbaUpdateController._logger.warning('Update information for Alba Node with IP {0} could not be updated'.format(alba_node.ip))
                information[alba_node.ip]['errors'].append('Connection timed out or connection refused on {0}'.format(alba_node.ip))
            except Exception as ex:
                information[alba_node.ip]['errors'].append(ex)

            alba_node.package_information = package_info
            alba_node.save()

    @staticmethod
    @add_hooks('update', 'merge_package_info')
    def merge_package_information_alba_plugin():
        """
        Retrieve the package information for the ALBA plugin, so the core code can merge it all together
        :return: Package information for ALBA nodes
        """
        package_info = {}
        for node in AlbaNodeList.get_albanodes():
            package_info[node.ip] = node.package_information
        return package_info

    @staticmethod
    @add_hooks('update', 'information')
    def get_update_information_alba_plugin(information):
        """
        Retrieve the update information for all StorageRouters for the ALBA plugin packages
        """
        # Verify arakoon downtime
        arakoon_ovs_down = False
        cluster_name = ArakoonClusterConfig.get_cluster_name('ovsdb')
        arakoon_metadata = ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=cluster_name)
        if arakoon_metadata['internal'] is True:
            config = ArakoonClusterConfig(cluster_id=cluster_name, filesystem=False)
            config.load_config()
            arakoon_ovs_down = len(config.nodes) < 3

        # Verify StorageRouter downtime
        fwk_prerequisites = []
        all_storagerouters = StorageRouterList.get_storagerouters()
        for storagerouter in all_storagerouters:
            try:
                SSHClient(endpoint=storagerouter, username='root')
            except UnableToConnectException:
                fwk_prerequisites.append(['node_down', storagerouter.name])

        # Verify ALBA node responsiveness
        alba_prerequisites = []
        for alba_node in AlbaNodeList.get_albanodes():
            try:
                alba_node.client.get_metadata()
            except Exception:
                alba_prerequisites.append(['alba_node_unresponsive', alba_node.ip])

        ips_covered = []
        for key in ['framework', 'alba']:
            if key not in information:
                information[key] = {'packages': [],
                                    'downtime': [],
                                    'prerequisites': fwk_prerequisites if key == 'framework' else alba_prerequisites,
                                    'services_stop_start': set(),
                                    'services_post_update': set()}

            for storagerouter in StorageRouterList.get_storagerouters():
                ips_covered.append(storagerouter.ip)
                if key not in storagerouter.package_information:
                    continue

                # Retrieve Arakoon issues
                arakoon_downtime = []
                arakoon_services = []
                for service in storagerouter.services:
                    if service.type.name not in [ServiceType.SERVICE_TYPES.ALBA_MGR, ServiceType.SERVICE_TYPES.NS_MGR]:
                        continue

                    if Configuration.exists('/ovs/arakoon/{0}/config'.format(service.name), raw=True) is False:
                        continue
                    arakoon_metadata = ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=service.name)
                    if arakoon_metadata['internal'] is True:
                        arakoon_services.append('ovs-arakoon-{0}'.format(service.name))
                        config = ArakoonClusterConfig(cluster_id=service.name, filesystem=False)
                        config.load_config()
                        if len(config.nodes) < 3:
                            if service.type.name == ServiceType.SERVICE_TYPES.NS_MGR:
                                arakoon_downtime.append(['backend', service.nsm_service.alba_backend.name])
                            else:
                                arakoon_downtime.append(['backend', service.abm_service.alba_backend.name])

                packages_to_check = storagerouter.package_information[key]
                for package_info in packages_to_check:
                    package_name = package_info.get('name')
                    covered_packages = [pkg['name'] for pkg in information[key]['packages']]
                    if package_name not in AlbaUpdateController.alba_plugin_packages:
                        continue  # Only gather information for the core packages

                    # noinspection PyTypeChecker
                    services_to_restart = package_info.pop('services_to_restart')
                    information[key]['services_post_update'].update(services_to_restart)
                    if package_name not in covered_packages and len(services_to_restart) == 0:  # Services to restart is only populated when installed version == candidate version, but some services require a restart
                        information[key]['packages'].append(package_info)

                    if package_name == 'openvstorage-backend':
                        information[key]['downtime'].append(['gui', None])
                        information[key]['services_stop_start'].update({'watcher-framework', 'memcached'})
                    elif package_name == 'arakoon':
                        if key == 'framework':
                            information[key]['services_post_update'].update({'ovs-arakoon-{0}'.format(ArakoonClusterConfig.get_cluster_name('ovsdb'))})
                            if arakoon_ovs_down is True:
                                information[key]['downtime'].append(['ovsdb', None])
                        else:
                            information[key]['downtime'].extend(arakoon_downtime)
                            information[key]['services_post_update'].update(arakoon_services)

            for alba_node in AlbaNodeList.get_albanodes():
                for package_info in alba_node.package_information.get(key, []):
                    package_name = package_info.get('name')
                    covered_packages = [pkg['name'] for pkg in information[key]['packages']]
                    if package_name not in AlbaUpdateController.sdm_packages:
                        continue  # Only gather information for the core packages

                    # noinspection PyTypeChecker
                    services_to_restart = package_info.pop('services_to_restart')
                    information[key]['services_post_update'].update(services_to_restart)
                    if package_name not in covered_packages and len(services_to_restart) == 0:  # Services to restart is only populated when installed version == candidate version, but some services require a restart
                        information[key]['packages'].append(package_info)
        return information

    @staticmethod
    @add_hooks('update', 'package_install_multi')
    def package_install_alba_plugin(client, package_names):
        """
        Update the Alba plugin packages
        :param client: Client on which to execute update the packages
        :type client: SSHClient
        :param package_names: Packages to install
        :type package_names: list
        :return: None
        """
        for package_name in package_names:
            if package_name in AlbaUpdateController.alba_plugin_packages:
                PackageManager.install(package_name=package_name, client=client)

    @staticmethod
    @add_hooks('update', 'package_install_single')
    def package_install_sdm(package_names):
        """
        Update the SDM packages
        :param package_names: Packages to install
        :type package_names: list
        :return: None
        """
        if set(package_names).intersection(AlbaUpdateController.sdm_packages):
            for alba_node in AlbaNodeList.get_albanodes():
                AlbaUpdateController._logger.debug('Updating SDM on ALBA node {0}'.format(alba_node.ip))
                try:
                    alba_node.client.execute_update(status=None)
                    AlbaUpdateController._logger.debug('Updated SDM on ALBA node {0}'.format(alba_node.ip))
                except requests.ConnectionError as ce:
                    if 'Connection aborted.' not in ce.message:  # This error is thrown due the post-update code of the SDM package which restarts the asd-manager service
                        raise
                    else:
                        AlbaUpdateController._logger.debug('Updated SDM on ALBA node {0}'.format(alba_node.ip))

    @staticmethod
    @add_hooks('update', 'post_update_multi')
    def post_update_alba_plugin_framework(client, components):
        """
        Execute functionality after the openvstorage-backend core packages have been updated
        For framework:
            * Restart arakoon-ovsdb on every client (if present and required)
        :param client: Client on which to execute this post update functionality
        :type client: SSHClient
        :param components: Update components which have been executed
        :type components: list
        :return: None
        """
        if 'framework' not in components or 'alba' not in components:
            return

        update_information = AlbaUpdateController.get_update_information_alba_plugin({})
        services_to_restart = set()
        if 'alba' in components:
            services_to_restart.update(update_information.get('alba', {}).get('services_post_update', set()))
        if 'framework' in components:
            services_to_restart.update(update_information.get('framework', {}).get('services_post_update', set()))

        # Restart Arakoon (and other services)
        for service_name in services_to_restart:
            if not service_name.startswith('ovs-arakoon-'):
                UpdateController.change_services_state(services=[service_name], ssh_clients=[client], action='restart')
            else:
                cluster_name = ArakoonClusterConfig.get_cluster_name(Toolbox.remove_prefix(service_name, 'ovs-arakoon-'))
                arakoon_metadata = ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=cluster_name)
                if arakoon_metadata['internal'] is True:
                    AlbaUpdateController._logger.debug('Restarting arakoon node {0}'.format(cluster_name), client_ip=client.ip)
                    ArakoonInstaller.restart_node(cluster_name=cluster_name,
                                                  client=client)

    @staticmethod
    @add_hooks('update', 'post_update_single')
    def post_update_alba_plugin_alba(components):
        """
        Execute some functionality after the ALBA plugin packages have been updated
        For alba:
            * Restart arakoon-amb, arakoon-nsm on every client (if present and required)
            * Execute post-update functionality on every ALBA node
        :param components: Update components which have been executed
        :type components: list
        :return: None
        """
        if 'alba' not in components:
            return

        # Update ALBA nodes
        for node in AlbaNodeList.get_albanodes():
            update_info = node.client.get_update_information()
            for component, package_info in update_info.iteritems():
                if len(package_info) > 0:
                    AlbaUpdateController._logger.debug('{0}: Restarting services'.format(node.ip))
                    node.client.restart_services()

        # Renew maintenance services
        AlbaUpdateController._logger.debug('Checkup maintenance agents')
        AlbaController.checkup_maintenance_agents.delay()
