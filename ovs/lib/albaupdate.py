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

import copy
import inspect
import requests
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.hybrids.servicetype import ServiceType
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs.extensions.db.arakooninstaller import ArakoonInstaller
from ovs.extensions.generic.logger import Logger
from ovs.extensions.generic.sshclient import SSHClient
from ovs_extensions.generic.toolbox import ExtensionsToolbox
from ovs.extensions.packages.albapackagefactory import PackageFactory
from ovs.extensions.services.albaservicefactory import ServiceFactory
from ovs.lib.alba import AlbaController
from ovs.lib.helpers.decorators import add_hooks
from ovs.lib.update import UpdateController


class AlbaUpdateController(object):
    """
    This class contains all logic for updating an environment
    """
    _logger = Logger(name='update', forced_target_type='file')
    _package_manager = PackageFactory.get_manager()
    _service_manager = ServiceFactory.get_manager()

    #########
    # HOOKS #
    #########
    @classmethod
    @add_hooks('update', 'get_package_info_cluster')
    def _get_package_information_cluster_alba(cls, client, package_info):
        """
        Retrieve information about the currently installed versions of the core packages
        Retrieve information about the versions to which each package can potentially be updated
        This information is combined for all plugins and further used in the GenericController.refresh_package_information call

        :param client: Client on which to collect the version information
        :type client: ovs.extensions.generic.sshclient.SSHClient
        :param package_info: Dictionary passed in by the thread calling this function
        :type package_info: dict
        :return: None
        :rtype: NoneType
        """
        cls._logger.info('StorageRouter {0}: Refreshing ALBA package information'.format(client.ip))
        try:
            if client.username != 'root':
                raise RuntimeError('Only the "root" user can retrieve the package information')

            # This also validates whether the required packages have been installed and unexpected packages have not been installed
            packages_to_update = PackageFactory.get_packages_to_update(client=client)
            cls._logger.debug('StorageRouter {0}: ALBA packages with updates: {1}'.format(client.ip, packages_to_update))
            for component, pkg_info in packages_to_update.iteritems():
                if component not in package_info[client.ip]:
                    package_info[client.ip][component] = pkg_info
                else:
                    for package_name, package_versions in pkg_info.iteritems():
                        package_info[client.ip][component][package_name] = package_versions
            cls._logger.info('StorageRouter {0}: Refreshed ALBA package information'.format(client.ip))
        except Exception as ex:
            cls._logger.exception('StorageRouter {0}: Refreshing ALBA package information failed'.format(client.ip))
            if 'errors' not in package_info[client.ip]:
                package_info[client.ip]['errors'] = []
            package_info[client.ip]['errors'].append(ex)

    @classmethod
    @add_hooks('update', 'get_update_info_cluster')
    def _get_update_information_cluster_alba(cls, client, update_info, package_info):
        """
        In this function the services for each component / package combination are defined
        This service information consists out of:
            * Services to stop (before update) and start (after update of packages) -> 'services_stop_start'
            * Services to restart after update (post-update logic)                  -> 'services_post_update'
            * Down-times which will be caused due to service restarts               -> 'downtime'
            * Prerequisites that have not been met                                  -> 'prerequisites'

        Verify whether all relevant services have the correct binary active
        Whether a service has the correct binary version in use, we use the ServiceFactory.verify_restart_required functionality
        When a service has an older binary version running, we add this information to the 'update_info'

        This combined information is then stored in the 'package_information' of the StorageRouter DAL object

        :param client: SSHClient on which to retrieve the service information required for an update
        :type client: ovs.extensions.generic.sshclient.SSHClient
        :param update_info: Dictionary passed in by the thread calling this function used to store all update information
        :type update_info: dict
        :param package_info: Dictionary containing the components and packages which have an update available for current SSHClient
        :type package_info: dict
        :return: None
        :rtype: NoneType
        """
        cls._logger.info('StorageRouter {0}: Refreshing ALBA update information'.format(client.ip))
        try:
            binaries = cls._package_manager.get_binary_versions(client=client)
            storagerouter = StorageRouterList.get_by_ip(ip=client.ip)
            cls._logger.debug('StorageRouter {0}: Binary versions: {1}'.format(client.ip, binaries))

            # Retrieve Arakoon information
            arakoon_info = {}
            for service in storagerouter.services:
                if service.type.name not in [ServiceType.SERVICE_TYPES.ALBA_MGR, ServiceType.SERVICE_TYPES.NS_MGR]:
                    continue

                if service.type.name == ServiceType.SERVICE_TYPES.ALBA_MGR:
                    cluster_name = service.abm_service.abm_cluster.name
                    alba_backend_name = service.abm_service.abm_cluster.alba_backend.name
                else:
                    cluster_name = service.nsm_service.nsm_cluster.name
                    alba_backend_name = service.nsm_service.nsm_cluster.alba_backend.name

                cls._logger.debug('StorageRouter {0}: Retrieving update information for Arakoon cluster {1}'.format(client.ip, cluster_name))
                arakoon_update_info = ArakoonInstaller.get_arakoon_update_info(cluster_name=cluster_name)
                cls._logger.debug('StorageRouter {0}: Arakoon update information for cluster {1}: {2}'.format(client.ip, cluster_name, arakoon_update_info))
                if arakoon_update_info['internal'] is True:
                    arakoon_info[arakoon_update_info['service_name']] = ['backend', alba_backend_name] if arakoon_update_info['downtime'] is True else None

            for component, package_names in PackageFactory.get_package_info()['names'].iteritems():
                package_names = sorted(package_names)
                cls._logger.debug('StorageRouter {0}: Validating component {1} and related packages: {2}'.format(client.ip, component, package_names))

                if component not in update_info[client.ip]:
                    update_info[client.ip][component] = copy.deepcopy(ServiceFactory.DEFAULT_UPDATE_ENTRY)
                svc_component_info = update_info[client.ip][component]
                pkg_component_info = package_info.get(component, {})

                for package_name in package_names:
                    cls._logger.debug('StorageRouter {0}: Validating ALBA plugin related package {1}'.format(client.ip, package_name))
                    if package_name == PackageFactory.PKG_OVS_BACKEND and package_name in pkg_component_info:
                        if ['gui', None] not in svc_component_info['downtime']:
                            svc_component_info['downtime'].append(['gui', None])
                        if ['api', None] not in svc_component_info['downtime']:
                            svc_component_info['downtime'].append(['api', None])
                        svc_component_info['services_stop_start'][10].append('ovs-watcher-framework')
                        svc_component_info['services_stop_start'][20].append('memcached')
                        cls._logger.debug('StorageRouter {0}: Added services "ovs-watcher-framework" and "memcached" to stop-start services'.format(client.ip))
                        cls._logger.debug('StorageRouter {0}: Added GUI and API to downtime'.format(client.ip))

                    elif package_name in [PackageFactory.PKG_ALBA, PackageFactory.PKG_ALBA_EE]:
                        # Retrieve proxy service information
                        for service in storagerouter.services:
                            if service.type.name != ServiceType.SERVICE_TYPES.ALBA_PROXY or service.alba_proxy is None:
                                continue

                            service_version = None
                            if package_name not in pkg_component_info:
                                service_version = ServiceFactory.verify_restart_required(client=client, service_name=service.name, binary_versions=binaries)

                            cls._logger.debug('StorageRouter {0}: Service {1} is running version {2}'.format(client.ip, service.name, service_version))
                            if package_name in pkg_component_info or service_version is not None:
                                if service_version is not None and package_name not in svc_component_info['packages']:
                                    svc_component_info['packages'][package_name] = service_version
                                svc_component_info['services_post_update'][10].append('ovs-{0}'.format(service.name))
                                cls._logger.debug('StorageRouter {0}: Added service {1} to post-update services'.format(client.ip, 'ovs-{0}'.format(service.name)))

                                downtime = ['proxy', service.alba_proxy.storagedriver.vpool.name]
                                if downtime not in svc_component_info['downtime']:
                                    svc_component_info['downtime'].append(downtime)
                                    cls._logger.debug('StorageRouter {0}: Added ALBA proxy downtime for vPool {1} to downtime'.format(client.ip, service.alba_proxy.storagedriver.vpool.name))

                    if package_name in [PackageFactory.PKG_ALBA, PackageFactory.PKG_ALBA_EE, PackageFactory.PKG_ARAKOON]:
                        for service_name, downtime in arakoon_info.iteritems():
                            service_version = ServiceFactory.verify_restart_required(client=client, service_name=service_name, binary_versions=binaries)
                            cls._logger.debug('StorageRouter {0}: Arakoon service {1} information: {2}'.format(client.ip, service_name, service_version))

                            if package_name in pkg_component_info or service_version is not None:
                                svc_component_info['services_post_update'][10].append('ovs-{0}'.format(service_name))
                                cls._logger.debug('StorageRouter {0}: Added service {1} to post-update services'.format(client.ip, 'ovs-{0}'.format(service_name)))
                                if service_version is not None and package_name not in svc_component_info['packages']:
                                    svc_component_info['packages'][package_name] = service_version
                                if downtime is not None and downtime not in svc_component_info['downtime']:
                                    svc_component_info['downtime'].append(downtime)
                                    cls._logger.debug('StorageRouter {0}: Added Arakoon cluster for ALBA Backend {1} to downtime'.format(client.ip, downtime[1]))

                    # Extend the service information with the package information related to this repository for current StorageRouter
                    if package_name in pkg_component_info and package_name not in svc_component_info['packages']:
                        cls._logger.debug('StorageRouter {0}: Adding package {1} because it has an update available'.format(client.ip, package_name))
                        svc_component_info['packages'][package_name] = pkg_component_info[package_name]

                if component == PackageFactory.COMP_ALBA:
                    for alba_node in AlbaNodeList.get_albanodes():
                        try:
                            alba_node.client.get_metadata()
                        except:
                            svc_component_info['prerequisites'].append(['alba_node_unresponsive', alba_node.ip])
                            cls._logger.debug('StorageRouter {0}: Added unresponsive ALBA Node {1} to prerequisites'.format(client.ip, alba_node.ip))
            cls._logger.info('StorageRouter {0}: Refreshed ALBA update information'.format(client.ip))
        except Exception as ex:
            cls._logger.exception('StorageRouter {0}: Refreshing ALBA update information failed'.format(client.ip))
            if 'errors' not in update_info[client.ip]:
                update_info[client.ip]['errors'] = []
            update_info[client.ip]['errors'].append(ex)

    @classmethod
    @add_hooks('update', 'get_update_info_plugin')
    def _get_update_information_plugin_alba(cls, error_information):
        """
        Called by GenericController.refresh_package_information() every hour
        Retrieve and store the update information for all AlbaNodes
        :param error_information: Dict passed in by the thread to collect all errors
        :type error_information: dict
        :return: None
        :rtype: NoneType
        """
        cls._logger.info('Refreshing ALBA plugin update information')

        error_count = 0
        for alba_node in AlbaNodeList.get_albanodes():
            if alba_node.type == AlbaNode.NODE_TYPES.GENERIC:
                continue

            cls._logger.debug('ALBA Node {0}: Refreshing update information'.format(alba_node.ip))
            if alba_node.ip not in error_information:
                error_information[alba_node.ip] = []

            try:
                update_info = alba_node.client.get_package_information()
                update_info_copy = copy.deepcopy(update_info)
                cls._logger.debug('ALBA Node {0}: Update information: {1}'.format(alba_node.ip, update_info))
                for component, info in update_info_copy.iteritems():
                    if len(info['packages']) == 0:
                        update_info.pop(component)
                cls._logger.debug('ALBA Node {0}: Storing update information: {1}'.format(alba_node.ip, update_info))
                alba_node.package_information = update_info
                alba_node.save()
                cls._logger.debug('ALBA Node {0}: Refreshed update information')
            except (requests.ConnectionError, requests.Timeout):
                error_count += 1
                cls._logger.warning('ALBA Node {0}: Update information could not be updated'.format(alba_node.ip))
                error_information[alba_node.ip].append('Connection timed out or connection refused on {0}'.format(alba_node.ip))
            except Exception as ex:
                error_count += 1
                cls._logger.exception('ALBA Node {0}: Update information could not be updated'.format(alba_node.ip))
                error_information[alba_node.ip].append(ex)
        if error_count == 0:
            cls._logger.info('Refreshed ALBA plugin update information')

    @classmethod
    @add_hooks('update', 'merge_package_info')
    def _merge_package_information_alba(cls):
        """
        Retrieve the information stored in the 'package_information' property on the ALBA Node DAL object
        This actually returns all information stored in the 'package_information' property including downtime info, prerequisites, services, ...
        The caller of this function will strip out and merge the relevant package information
        :return: Update information for all ALBA Nodes
        :rtype: dict
        """
        cls._logger.debug('Retrieving package information for ALBA plugin')
        update_info = {}
        for alba_node in AlbaNodeList.get_albanodes():
            if alba_node.type == AlbaNode.NODE_TYPES.GENERIC:
                continue
            update_info[alba_node.ip] = alba_node.package_information
        cls._logger.debug('Retrieved package information for ALBA plugin')
        return update_info

    @classmethod
    @add_hooks('update', 'merge_downtime_info')
    def _merge_downtime_information_alba(cls):
        """
        Called when the 'Update' button in the GUI is pressed
        This call merges the downtime and prerequisite information present in the 'package_information' property for each ALBA Node DAL object
        :return: Information about prerequisites not met and downtime issues
        :rtype: dict
        """
        cls._logger.debug('Retrieving downtime and prerequisite information for ALBA plugin')
        merged_update_info = {}
        for alba_node in AlbaNodeList.get_albanodes():
            for component_name, component_info in alba_node.package_information.iteritems():
                if component_name not in merged_update_info:
                    merged_update_info[component_name] = {'downtime': [],
                                                          'prerequisites': []}
                for downtime in component_info['downtime']:
                    if downtime not in merged_update_info[component_name]['downtime']:
                        merged_update_info[component_name]['downtime'].append(downtime)
                for prerequisite in component_info['prerequisites']:
                    if prerequisite not in merged_update_info[component_name]['prerequisites']:
                        merged_update_info[component_name]['prerequisites'].append(prerequisite)
        cls._logger.debug('Retrieved downtime and prerequisite information for ALBA plugin: {0}'.format(merged_update_info))
        return merged_update_info

    @classmethod
    @add_hooks('update', 'package_install_multi')
    def _package_install_alba_plugin(cls, client, package_info, components=None):
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
        return PackageFactory.update_packages(client=client, packages=package_info, components=components)

    @classmethod
    @add_hooks('update', 'package_install_single')
    def _package_install_sdm(cls, package_info, components=None):
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
            components = [PackageFactory.COMP_ALBA]

        if PackageFactory.COMP_ALBA not in components:
            return False

        abort = False
        alba_nodes = [alba_node for alba_node in AlbaNodeList.get_albanodes() if alba_node.type == AlbaNode.NODE_TYPES.ASD]
        alba_nodes.sort(key=lambda node: ExtensionsToolbox.advanced_sort(element=node.ip, separator='.'))
        for alba_node in alba_nodes:
            for pkg_name, pkg_info in alba_node.package_information.get(PackageFactory.COMP_ALBA, {}).iteritems():
                try:
                    installed = pkg_info['installed']
                    candidate = pkg_info['candidate']

                    if candidate == alba_node.client.update_installed_version_package(package_name=pkg_name):
                        # Package has already been installed by another hook
                        continue

                    cls._logger.info('{0}: Updating package {1} ({2} --> {3})'.format(alba_node.ip, pkg_name, installed, candidate))
                    alba_node.client.execute_update(pkg_name)
                    cls._logger.info('{0}: Updated package {1}'.format(alba_node.ip, pkg_name))
                except requests.ConnectionError as ce:
                    if 'Connection aborted.' not in ce.message:  # This error is thrown due the post-update code of the SDM package which restarts the asd-manager service
                        raise
                except Exception:
                    cls._logger.exception('{0}: Failed to update package {1}'.format(alba_node.ip, pkg_name))
                    abort = True
        return abort

    @classmethod
    @add_hooks('update', 'post_update_multi')
    def _post_update_alba_plugin_framework(cls, client, components, update_information=None):
        """
        Execute functionality after the openvstorage-backend core packages have been updated
        For ALBA:
            * Restart ABM arakoons on every client (if present and required)
            * Restart NSM arakoons on every client (if present and required)
        :param client: Client on which to execute this post update functionality
        :type client: SSHClient
        :param components: Update components which have been executed
        :type components: list
        :param update_information: Information required for an update (defaults to None for backwards compatibility)
        :type update_information: dict
        :return: None
        :rtype: NoneType
        """
        method_name = inspect.currentframe().f_code.co_name
        cls._logger.info('{0}: Executing hook {1}'.format(client.ip, method_name))
        pkg_names_to_check = set()
        for component, package_names in PackageFactory.get_package_info()['names'].iteritems():
            if component in components:
                pkg_names_to_check.update(package_names)

        try:
            ServiceFactory.remove_services_marked_for_removal(client=client,
                                                              package_names=pkg_names_to_check)
        except Exception:
            cls._logger.exception('{0}: Removing the services marked for removal failed'.format(client.ip))

        if update_information is None:
            update_information = {}

        other_services = set()
        arakoon_services = set()
        for component, update_info in update_information.iteritems():
            if component not in PackageFactory.get_components():
                continue
            for restart_order in sorted(update_info['services_post_update']):
                for service_name in update_info['services_post_update'][restart_order]:
                    if service_name.startswith('arakoon-'):
                        arakoon_services.add(service_name)
                    else:
                        other_services.add(service_name)

        UpdateController.change_services_state(services=sorted(other_services), ssh_clients=[client], action='restart')
        for service_name in sorted(arakoon_services):
            try:
                cluster_name = ArakoonInstaller.get_cluster_name(ExtensionsToolbox.remove_prefix(service_name, 'arakoon-'))
                arakoon_metadata = ArakoonInstaller.get_arakoon_update_info(cluster_name=cluster_name)
                if arakoon_metadata['internal'] is True:
                    arakoon_installer = ArakoonInstaller(cluster_name=cluster_name)
                    arakoon_installer.load()
                    if client.ip in [node.ip for node in arakoon_installer.config.nodes]:
                        cls._logger.warning('{0}: Restarting arakoon node {1}'.format(client.ip, cluster_name))
                        arakoon_installer.restart_node(client=client)
            except Exception:
                cls._logger.exception('{0}: Restarting service {1} failed'.format(client.ip, service_name))

        cls._logger.info('{0}: Executed hook {1}'.format(client.ip, method_name))

    @classmethod
    @add_hooks('update', 'post_update_single')
    def _post_update_alba_plugin_alba(cls, components):
        """
        Execute some functionality after the ALBA plugin packages have been updated
        For alba:
            * Restart arakoon-amb, arakoon-nsm on every client (if present and required)
            * Execute post-update functionality on every ALBA node
        :param components: Update components which have been executed
        :type components: list
        :return: None
        :rtype: NoneType
        """
        if PackageFactory.COMP_ALBA not in components:
            return

        # Update ALBA nodes
        method_name = inspect.currentframe().f_code.co_name
        cls._logger.info('Executing hook {0}'.format(method_name))
        alba_nodes = [alba_node for alba_node in AlbaNodeList.get_albanodes() if alba_node.type == AlbaNode.NODE_TYPES.ASD]
        alba_nodes.sort(key=lambda node: ExtensionsToolbox.advanced_sort(element=node.ip, separator='.'))
        for alba_node in alba_nodes:
            if PackageFactory.COMP_ALBA in alba_node.package_information and PackageFactory.PKG_MGR_SDM in alba_node.package_information[PackageFactory.COMP_ALBA]:
                cls._logger.info('{0}: Restarting services'.format(alba_node.ip))
                alba_node.client.restart_services()

        # Renew maintenance services
        cls._logger.info('Checkup maintenance agents')
        AlbaController.checkup_maintenance_agents.delay()

        # Run post-update migrations
        try:
            # noinspection PyUnresolvedReferences
            from ovs.lib.albamigration import AlbaMigrationController
            AlbaMigrationController.migrate.delay()
            AlbaMigrationController.migrate_sdm.delay()
        except ImportError:
            cls._logger.error('Could not import AlbaMigrationController')

        cls._logger.info('Executed hook {0}'.format(method_name))
