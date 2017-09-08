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

import os
import copy
import inspect
import requests
from distutils.version import LooseVersion
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.hybrids.servicetype import ServiceType
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs.extensions.db.arakooninstaller import ArakoonClusterConfig, ArakoonInstaller
from ovs_extensions.db.arakoon.pyrakoon.pyrakoon.compat import ArakoonNoMaster, ArakoonNotFound
from ovs.extensions.generic.configuration import Configuration
from ovs.extensions.generic.logger import Logger
from ovs.extensions.generic.sshclient import SSHClient, UnableToConnectException
from ovs.extensions.generic.system import System
from ovs_extensions.generic.toolbox import ExtensionsToolbox
from ovs.extensions.packages.packagefactory import PackageFactory
from ovs.extensions.services.servicefactory import ServiceFactory
from ovs.lib.alba import AlbaController
from ovs.lib.helpers.decorators import add_hooks
from ovs.lib.update import UpdateController

os.environ['OVS_LOGTYPE_OVERRIDE'] = 'file'  # Make sure we log to file during update


class AlbaUpdateController(object):
    """
    This class contains all logic for updating an environment
    """
    _logger = Logger('update')
    _packages_alba_plugin = {'alba': {'alba', 'alba-ee', 'openvstorage-sdm'},
                             'framework': {'alba', 'alba-ee', 'arakoon', 'openvstorage-backend'}}
    _packages_alba_plugin_all = _packages_alba_plugin['alba'].union(_packages_alba_plugin['framework'])
    _packages_alba_plugin_binaries = {'alba', 'alba-ee', 'arakoon'}
    _packages_alba_plugin_blocking = _packages_alba_plugin['framework'].difference(_packages_alba_plugin_binaries)
    _packages_optional = {'openvstorage-sdm'}
    _packages_mutual_excl = [['alba', 'alba-ee']]

    #########
    # HOOKS #
    #########
    @staticmethod
    @add_hooks('update', 'get_package_info_multi')
    def _get_package_information_alba_plugin_storage_routers(client, package_info):
        """
        Called by GenericController.refresh_package_information() every hour

        Retrieve information about the currently installed versions of the core packages
        Retrieve information about the versions to which each package can potentially be updated
        If installed version is different from candidate version --> store this information in model

        Additionally check the services with a 'run' file
        Verify whether the running version is up-to-date with the candidate version
        If different --> store this information in the model

        Result: Every package with updates or which requires services to be restarted is stored in the model

        :param client: Client on which to collect the version information
        :type client: SSHClient
        :param package_info: Dictionary passed in by the thread calling this function
        :type package_info: dict
        :return: Package information
        :rtype: dict
        """
        from ovs_extensions.generic.toolbox import ExtensionsToolbox

        try:
            if client.username != 'root':
                raise RuntimeError('Only the "root" user can retrieve the package information')

            service_manager = ServiceFactory.get_manager()
            package_manager = PackageFactory.get_manager()
            binaries = package_manager.get_binary_versions(client=client, package_names=AlbaUpdateController._packages_alba_plugin_binaries)
            installed = package_manager.get_installed_versions(client=client, package_names=AlbaUpdateController._packages_alba_plugin_all)
            candidate = package_manager.get_candidate_versions(client=client, package_names=AlbaUpdateController._packages_alba_plugin_all)
            not_installed = set(AlbaUpdateController._packages_alba_plugin_all) - set(installed.keys())
            candidate_difference = set(AlbaUpdateController._packages_alba_plugin_all) - set(candidate.keys())

            for package_name in not_installed:
                found = False
                for entry in AlbaUpdateController._packages_mutual_excl:
                    if package_name in entry:
                        found = True
                        if entry[1 - entry.index(package_name)] in not_installed:
                            raise RuntimeError('Conflicting packages installed: {0}'.format(entry))
                if found is False:
                    if package_name in AlbaUpdateController._packages_optional:
                        continue
                    raise RuntimeError('Missing non-installed package: {0}'.format(package_name))
                if package_name not in candidate_difference:
                    raise RuntimeError('Unexpected difference in missing installed/candidates: {0}'.format(package_name))
                candidate_difference.remove(package_name)
            if len(candidate_difference) > 0:
                raise RuntimeError('No candidates available for some packages: {0}'.format(candidate_difference))

            # Retrieve Arakoon information
            framework_arakoons = []
            for cluster in ['cacc', 'ovsdb']:
                cluster_name = ArakoonClusterConfig.get_cluster_name(cluster)
                if cluster_name is None:
                    continue

                ip = client.ip if cluster == 'cacc' else None
                try:
                    arakoon_metadata = ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=cluster_name,
                                                                                             ip=ip)
                except ArakoonNoMaster:
                    raise RuntimeError('Arakoon cluster {0} does not have a master'.format(cluster))
                except ArakoonNotFound:
                    raise RuntimeError('Arakoon cluster {0} does not have the required metadata key'.format(cluster))

                if arakoon_metadata['internal'] is True:
                    framework_arakoons.append(ArakoonInstaller.get_service_name_for_cluster(cluster_name=arakoon_metadata['cluster_name']))

            storagerouter = StorageRouterList.get_by_ip(client.ip)
            alba_arakoons = []
            for service in storagerouter.services:
                if service.type.name == ServiceType.SERVICE_TYPES.ALBA_MGR or service.type.name == ServiceType.SERVICE_TYPES.NS_MGR:
                    alba_arakoons.append(service.name)

            alba_package = 'alba' if 'alba' in installed.keys() else 'alba-ee'
            version_mapping = {'alba': ['alba', 'alba-ee']}

            default_entry = {'candidate': None,
                             'installed': None,
                             'services_to_restart': []}

            #                       component:    package_name: services_with_run_file
            for component, info in {'framework': {'arakoon': framework_arakoons,
                                                  'openvstorage-backend': []},
                                    'alba': {alba_package: alba_arakoons,
                                             'arakoon': alba_arakoons}}.iteritems():
                component_info = {}
                for package, services in info.iteritems():
                    for service in services:
                        service = ExtensionsToolbox.remove_prefix(service, 'ovs-')
                        if not service_manager.has_service(service, client):
                            # There's no service, so no need to restart it
                            continue
                        package_name = package
                        version_file = '/opt/OpenvStorage/run/{0}.version'.format(service)
                        if not client.file_exists(version_file):
                            # The .version file was not found, so we don't know whether to restart it or not. Let's choose the safest option
                            AlbaUpdateController._logger.warning('{0}: Failed to find a version file in /opt/OpenvStorage/run for service {1}'.format(client.ip, service))
                            if package_name not in binaries:
                                raise RuntimeError('Binary version for package {0} was not retrieved'.format(package_name))
                            if package_name not in component_info:
                                component_info[package_name] = copy.deepcopy(default_entry)
                            component_info[package_name]['installed'] = '{0}-reboot'.format(binaries[package_name])
                            component_info[package_name]['candidate'] = str(binaries[package_name])
                            component_info[package_name]['services_to_restart'].append(service)
                            continue
                        # The .version file exists. Base restart requirement on its content
                        running_versions = client.file_read(version_file).strip()
                        for version in running_versions.split(';'):
                            version = version.strip()
                            running_version = None
                            if '=' in version:
                                package_name = version.split('=')[0]
                                running_version = version.split('=')[1]
                            elif version:
                                running_version = version

                            did_check = False
                            for mapped_package_name in version_mapping.get(package_name, [package_name]):
                                if mapped_package_name not in UpdateController.packages_core_all:
                                    raise ValueError('Unknown package dependency found in {0}'.format(version_file))
                                if mapped_package_name not in binaries or mapped_package_name not in installed:
                                    continue

                                did_check = True
                                if running_version is not None and LooseVersion(running_version) < binaries[mapped_package_name]:
                                    if package_name not in component_info:
                                        component_info[mapped_package_name] = copy.deepcopy(default_entry)
                                    component_info[mapped_package_name]['installed'] = running_version
                                    component_info[mapped_package_name]['candidate'] = str(binaries[mapped_package_name])
                                    component_info[mapped_package_name]['services_to_restart'].append('ovs-'.format(service))
                                    break
                            if did_check is False:
                                raise RuntimeError('Binary version for package {0} was not retrieved'.format(package_name))

                    if installed[package] < candidate[package] and package not in component_info:
                        component_info[package] = copy.deepcopy(default_entry)
                        component_info[package]['installed'] = str(installed[package])
                        component_info[package]['candidate'] = str(candidate[package])
                if component_info:
                    if component not in package_info[client.ip]:
                        package_info[client.ip][component] = {}
                    package_info[client.ip][component].update(component_info)
        except Exception as ex:
            AlbaUpdateController._logger.exception('Could not load update information')
            if 'errors' not in package_info[client.ip]:
                package_info[client.ip]['errors'] = []
            package_info[client.ip]['errors'].append(ex)
        return package_info

    @staticmethod
    @add_hooks('update', 'get_package_info_single')
    def _get_package_information_alba_plugin_storage_nodes(information):
        """
        Called by GenericController.refresh_package_information() every hour

        Retrieve and store the package information for all AlbaNodes
        :return: None
        """
        for alba_node in AlbaNodeList.get_albanodes():
            if alba_node.type == AlbaNode.NODE_TYPES.GENERIC:
                continue

            if alba_node.ip not in information:
                information[alba_node.ip] = {'errors': []}
            elif 'errors' not in information[alba_node.ip]:
                information[alba_node.ip]['errors'] = []

            try:
                alba_node.package_information = alba_node.client.get_package_information()
                alba_node.save()
            except (requests.ConnectionError, requests.Timeout):
                AlbaUpdateController._logger.warning('Update information for Alba Node with IP {0} could not be updated'.format(alba_node.ip))
                information[alba_node.ip]['errors'].append('Connection timed out or connection refused on {0}'.format(alba_node.ip))
            except Exception as ex:
                AlbaUpdateController._logger.exception('Update information for Alba Node with IP {0} could not be updated'.format(alba_node.ip))
                information[alba_node.ip]['errors'].append(ex)

    @staticmethod
    @add_hooks('update', 'merge_package_info')
    def _merge_package_information_alba_plugin():
        """
        Retrieve the package information for the ALBA plugin, so the core code can merge it all together
        :return: Package information for ALBA nodes
        """
        # Ignore generic nodes
        return dict((node.ip, node.package_information) for node in AlbaNodeList.get_albanodes() if node.type != AlbaNode.NODE_TYPES.GENERIC)

    @staticmethod
    @add_hooks('update', 'information')
    def _get_update_information_alba_plugin(information):
        """
        Called when the 'Update' button in the GUI is pressed
        This call collects additional information about the packages which can be updated
        Eg:
            * Downtime for Arakoons
            * Downtime for StorageDrivers
            * Prerequisites that haven't been met
            * Services which will be stopped during update
            * Services which will be restarted after update
        """
        # Verify arakoon info
        arakoon_ovs_info = {'down': False,
                            'name': None,
                            'internal': False}
        arakoon_cacc_info = {'down': False,
                             'name': None,
                             'internal': False}
        for cluster in ['cacc', 'ovsdb']:
            cluster_name = ArakoonClusterConfig.get_cluster_name(cluster)
            if cluster_name is None:
                continue

            ip = System.get_my_storagerouter().ip if cluster == 'cacc' else None
            try:
                arakoon_metadata = ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=cluster_name,
                                                                                         ip=ip)
            except ArakoonNoMaster:
                raise RuntimeError('Arakoon cluster {0} does not have a master'.format(cluster))
            except ArakoonNotFound:
                raise RuntimeError('Arakoon cluster {0} does not have the required metadata key'.format(cluster))

            if arakoon_metadata['internal'] is True:
                config = ArakoonClusterConfig(cluster_id=cluster_name,
                                              source_ip=ip)
                if cluster == 'ovsdb':
                    arakoon_ovs_info['down'] = len(config.nodes) < 3
                    arakoon_ovs_info['name'] = arakoon_metadata['cluster_name']
                    arakoon_ovs_info['internal'] = True
                else:
                    arakoon_cacc_info['name'] = arakoon_metadata['cluster_name']
                    arakoon_cacc_info['internal'] = True

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

        for key in ['framework', 'alba']:
            if key not in information:
                information[key] = {'packages': {},
                                    'downtime': [],
                                    'prerequisites': fwk_prerequisites if key == 'framework' else alba_prerequisites,
                                    'services_stop_start': set(),
                                    'services_post_update': set()}

            for storagerouter in StorageRouterList.get_storagerouters():
                if key not in storagerouter.package_information:
                    continue

                # Retrieve Arakoon issues
                arakoon_downtime = []
                arakoon_services = []
                for service in storagerouter.services:
                    if service.type.name not in [ServiceType.SERVICE_TYPES.ALBA_MGR, ServiceType.SERVICE_TYPES.NS_MGR]:
                        continue

                    if service.type.name == ServiceType.SERVICE_TYPES.ALBA_MGR:
                        cluster_name = service.abm_service.abm_cluster.name
                    else:
                        cluster_name = service.nsm_service.nsm_cluster.name
                    if Configuration.exists('/ovs/arakoon/{0}/config'.format(cluster_name), raw=True) is False:
                        continue
                    arakoon_metadata = ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=cluster_name)
                    if arakoon_metadata['internal'] is True:
                        arakoon_services.append('ovs-{0}'.format(service.name))
                        config = ArakoonClusterConfig(cluster_id=cluster_name)
                        if len(config.nodes) < 3:
                            if service.type.name == ServiceType.SERVICE_TYPES.NS_MGR:
                                arakoon_downtime.append(['backend', service.nsm_service.nsm_cluster.alba_backend.name])
                            else:
                                arakoon_downtime.append(['backend', service.abm_service.abm_cluster.alba_backend.name])

                for package_name, package_info in storagerouter.package_information[key].iteritems():
                    if package_name not in AlbaUpdateController._packages_alba_plugin['framework']:
                        continue  # Only gather information for the core packages

                    information[key]['services_post_update'].update(package_info.pop('services_to_restart'))
                    if package_name not in information[key]['packages']:
                        information[key]['packages'][package_name] = {}
                    information[key]['packages'][package_name].update(package_info)

                    if package_name == 'openvstorage-backend':
                        if ['gui', None] not in information[key]['downtime']:
                            information[key]['downtime'].append(['gui', None])
                        if ['api', None] not in information[key]['downtime']:
                            information[key]['downtime'].append(['api', None])
                        information[key]['services_stop_start'].update({'watcher-framework', 'memcached'})
                    elif package_name in ['alba', 'alba-ee']:
                        for down in arakoon_downtime:
                            if down not in information[key]['downtime']:
                                information[key]['downtime'].append(down)
                        information[key]['services_post_update'].update(arakoon_services)
                    elif package_name == 'arakoon':
                        if key == 'framework':
                            framework_arakoons = set()
                            if arakoon_ovs_info['internal'] is True:
                                framework_arakoons.add('ovs-arakoon-{0}'.format(arakoon_ovs_info['name']))
                            if arakoon_cacc_info['internal'] is True:
                                framework_arakoons.add('ovs-arakoon-{0}'.format(arakoon_cacc_info['name']))

                            information[key]['services_post_update'].update(framework_arakoons)
                            if arakoon_ovs_info['down'] is True and ['ovsdb', None] not in information[key]['downtime']:
                                information[key]['downtime'].append(['ovsdb', None])
                        else:
                            for down in arakoon_downtime:
                                if down not in information[key]['downtime']:
                                    information[key]['downtime'].append(down)
                            information[key]['services_post_update'].update(arakoon_services)

            for alba_node in AlbaNodeList.get_albanodes():
                for package_name, package_info in alba_node.package_information.get(key, {}).iteritems():
                    if package_name not in AlbaUpdateController._packages_alba_plugin['alba']:
                        continue  # Only gather information for the SDM packages

                    information[key]['services_post_update'].update(package_info.pop('services_to_restart'))
                    if package_name not in information[key]['packages']:
                        information[key]['packages'][package_name] = {}
                    information[key]['packages'][package_name].update(package_info)
        return information

    @staticmethod
    @add_hooks('update', 'package_install_multi')
    def _package_install_alba_plugin(client, package_info, components=None):
        """
        Update the Alba plugin packages
        :param client: Client on which to execute update the packages
        :type client: SSHClient
        :param package_info: Information about the packages (installed, candidate)
        :type package_info: dict
        :param components: Components which have been selected for update
        :type components: list
        :return: Boolean indicating whether to continue with the update or not
        :rtype: bool
        """
        if components is None:
            components = ['framework']

        if 'framework' not in components:
            return False

        abort = False
        package_manager = PackageFactory.get_manager()
        currently_installed_versions = package_manager.get_installed_versions(client=client, package_names=AlbaUpdateController._packages_alba_plugin_all)
        for pkg_name in sorted(AlbaUpdateController._packages_alba_plugin['framework']):
            if pkg_name in package_info:
                try:
                    installed = package_info[pkg_name]['installed']
                    candidate = package_info[pkg_name]['candidate']

                    if candidate == str(currently_installed_versions[pkg_name]):
                        # Package has already been installed by another hook
                        continue

                    AlbaUpdateController._logger.info('{0}: Updating package {1} ({2} --> {3})'.format(client.ip, pkg_name, installed, candidate))
                    package_manager.install(package_name=pkg_name, client=client)
                    AlbaUpdateController._logger.info('{0}: Updated package {1}'.format(client.ip, pkg_name))
                except Exception:
                    AlbaUpdateController._logger.exception('{0}: Updating package {1} failed'.format(client.ip, pkg_name))
                    if pkg_name in AlbaUpdateController._packages_alba_plugin_blocking:
                        abort = True
        return abort

    @staticmethod
    @add_hooks('update', 'package_install_single')
    def _package_install_sdm(package_info, components=None):
        """
        Update the SDM packages
        :param package_info: Unused
        :type package_info: dict
        :param components: Components which have been selected for update
        :type components: list
        :return: Boolean indicating whether to continue with the update or not
        :rtype: bool
        """
        _ = package_info
        if components is None:
            components = ['alba']

        if 'alba' not in components:
            return False

        abort = False
        alba_nodes = [alba_node for alba_node in AlbaNodeList.get_albanodes() if alba_node.type == AlbaNode.NODE_TYPES.ASD]
        alba_nodes.sort(key=lambda node: ExtensionsToolbox.advanced_sort(element=node.ip, separator='.'))
        for alba_node in alba_nodes:
            for pkg_name, pkg_info in alba_node.package_information.get('alba', {}).iteritems():
                try:
                    installed = pkg_info['installed']
                    candidate = pkg_info['candidate']

                    if candidate == alba_node.client.update_installed_version_package(package_name=pkg_name):
                        # Package has already been installed by another hook
                        continue

                    AlbaUpdateController._logger.info('{0}: Updating package {1} ({2} --> {3})'.format(alba_node.ip, pkg_name, installed, candidate))
                    alba_node.client.execute_update(pkg_name)
                    AlbaUpdateController._logger.info('{0}: Updated package {1}'.format(alba_node.ip, pkg_name))
                except requests.ConnectionError as ce:
                    if 'Connection aborted.' not in ce.message:  # This error is thrown due the post-update code of the SDM package which restarts the asd-manager service
                        raise
                except Exception:
                    AlbaUpdateController._logger.exception('{0}: Failed to update package {1}'.format(alba_node.ip, pkg_name))
                    abort = True
        return abort

    @staticmethod
    @add_hooks('update', 'post_update_multi')
    def _post_update_alba_plugin_framework(client, components):
        """
        Execute functionality after the openvstorage-backend core packages have been updated
        For framework:
            * Restart arakoon-ovsdb on every client (if present and required)
            * Restart arakoon-config on every client (if present and required)
        For ALBA:
            * Restart ABM arakoons on every client (if present and required)
            * Restart NSM arakoons on every client (if present and required)
        :param client: Client on which to execute this post update functionality
        :type client: SSHClient
        :param components: Update components which have been executed
        :type components: list
        :return: None
        """
        if 'framework' not in components and 'alba' not in components:
            return

        from ovs_extensions.generic.toolbox import ExtensionsToolbox

        update_information = AlbaUpdateController._get_update_information_alba_plugin({})
        services_to_restart = set()
        if 'alba' in components:
            services_to_restart.update(update_information.get('alba', {}).get('services_post_update', set()))
        if 'framework' in components:
            services_to_restart.update(update_information.get('framework', {}).get('services_post_update', set()))

        # Restart Arakoon (and other services)
        if services_to_restart:
            AlbaUpdateController._logger.info('{0}: Executing hook {1}'.format(client.ip, inspect.currentframe().f_code.co_name))
            for service_name in sorted(services_to_restart):
                if not service_name.startswith('arakoon-'):
                    UpdateController.change_services_state(services=[service_name], ssh_clients=[client], action='restart')
                else:
                    cluster_name = ArakoonClusterConfig.get_cluster_name(internal_name=ExtensionsToolbox.remove_prefix(service_name, 'arakoon-'))
                    master_ip = StorageRouterList.get_masters()[0].ip if cluster_name == 'config' else None
                    temp_cluster_name = 'cacc' if cluster_name == 'config' else cluster_name
                    try:
                        arakoon_metadata = ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=temp_cluster_name,
                                                                                                 ip=master_ip)
                    except ArakoonNoMaster:
                        AlbaUpdateController._logger.warning('Arakoon cluster {0} does not have a master, not restarting related services'.format(cluster_name))
                        continue
                    except ArakoonNotFound:
                        AlbaUpdateController._logger.warning('Arakoon cluster {0} does not have the required metadata key, not restarting related services'.format(cluster_name))
                        continue

                    if arakoon_metadata['internal'] is True:
                        arakoon_installer = ArakoonInstaller(cluster_name=cluster_name)
                        arakoon_installer.load(ip=master_ip)
                        arakoon_installer.restart_cluster()
            AlbaUpdateController._logger.info('{0}: Executed hook {1}'.format(client.ip, inspect.currentframe().f_code.co_name))

    @staticmethod
    @add_hooks('update', 'post_update_single')
    def _post_update_alba_plugin_alba(components):
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
        AlbaUpdateController._logger.info('Executing hook {0}'.format(inspect.currentframe().f_code.co_name))
        alba_nodes = AlbaNodeList.get_albanodes()
        alba_nodes.sort(key=lambda node: ExtensionsToolbox.advanced_sort(element=node.ip, separator='.'))
        for alba_node in alba_nodes:
            if alba_node.client.get_package_information():
                AlbaUpdateController._logger.info('{0}: Restarting services'.format(alba_node.ip))
                alba_node.client.restart_services()

        # Renew maintenance services
        AlbaUpdateController._logger.info('Checkup maintenance agents')
        AlbaController.checkup_maintenance_agents.delay()

        # Run post-update migrations
        try:
            # noinspection PyUnresolvedReferences
            from ovs.lib.albamigration import AlbaMigrationController
            AlbaMigrationController.migrate.delay()
            AlbaMigrationController.migrate_sdm.delay()
        except ImportError:
            AlbaUpdateController._logger.error('Could not import AlbaMigrationController')

        AlbaUpdateController._logger.info('Executed hook {0}'.format(inspect.currentframe().f_code.co_name))
