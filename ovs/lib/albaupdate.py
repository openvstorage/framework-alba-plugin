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
    @add_hooks('update', 'get_package_info_multi')
    def _get_package_information_alba_plugin_storage_routers(cls, client, package_info):
        """
        Called by GenericController.refresh_package_information() every hour

        Retrieve information about the currently installed versions of the core packages
        Retrieve information about the versions to which each package can potentially be updated
        If installed version is different from candidate version --> store this information in model

        Additionally if installed version is identical to candidate version, check the services with a 'run' file
        Verify whether the running version is identical to the candidate version
        If different --> store this information in the model

        Result: Every package with updates or which requires services to be restarted is stored in the model

        :param client: Client on which to collect the version information
        :type client: ovs_extensions.generic.sshclient.SSHClient
        :param package_info: Dictionary passed in by the thread calling this function
        :type package_info: dict
        :return: Package information
        :rtype: dict
        """
        try:
            if client.username != 'root':
                raise RuntimeError('Only the "root" user can retrieve the package information')

            binaries = cls._package_manager.get_binary_versions(client=client)
            service_info = ServiceFactory.get_services_with_version_files(storagerouter=StorageRouterList.get_by_ip(ip=client.ip))
            packages_to_update = PackageFactory.get_packages_to_update(client=client)
            services_to_update = ServiceFactory.get_services_to_update(client=client,
                                                                       binaries=binaries,
                                                                       service_info=service_info)

            # First we merge in the services
            ExtensionsToolbox.merge_dicts(dict1=package_info[client.ip],
                                          dict2=services_to_update)
            # Then the packages merge can potentially overrule the installed/candidate version, because these versions need priority over the service versions
            ExtensionsToolbox.merge_dicts(dict1=package_info[client.ip],
                                          dict2=packages_to_update)
        except Exception as ex:
            AlbaUpdateController._logger.exception('Could not load update information')
            if 'errors' not in package_info[client.ip]:
                package_info[client.ip]['errors'] = []
            package_info[client.ip]['errors'].append(ex)
        return package_info

    @classmethod
    @add_hooks('update', 'get_package_info_single')
    def _get_package_information_alba_plugin_storage_nodes(cls, information):
        """
        Called by GenericController.refresh_package_information() every hour

        Retrieve and store the package information for all AlbaNodes
        :return: None
        :rtype: NoneType
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
                cls._logger.warning('Update information for Alba Node with IP {0} could not be updated'.format(alba_node.ip))
                information[alba_node.ip]['errors'].append('Connection timed out or connection refused on {0}'.format(alba_node.ip))
            except Exception as ex:
                cls._logger.exception('Update information for Alba Node with IP {0} could not be updated'.format(alba_node.ip))
                information[alba_node.ip]['errors'].append(ex)

    @classmethod
    @add_hooks('update', 'merge_package_info')
    def _merge_package_information_alba_plugin(cls):
        """
        Retrieve the package information for the ALBA plugin, so the core code can merge it all together
        :return: Package information for ALBA nodes
        :rtype: dict
        """
        # Ignore generic nodes
        return dict((node.ip, node.package_information) for node in AlbaNodeList.get_albanodes() if node.type != AlbaNode.NODE_TYPES.GENERIC)

    @classmethod
    @add_hooks('update', 'information')
    def _get_update_information_alba_plugin(cls, information):
        """
        Called when the 'Update' button in the GUI is pressed
        This call collects additional information about the packages which can be updated
        Eg:
            * Downtime for Arakoons
            * Downtime for StorageDrivers
            * Prerequisites that haven't been met
            * Services which will be stopped during update
            * Services which will be restarted after update
        :param information: Information about all components for the entire cluster. This is passed in by the calling thread and thus also (pre-)populated by other threads
        :type information: dict
        :return: All the information collected
        :rtype: dict
        """
        # Verify ALBA node responsiveness
        alba_prerequisites = []
        for alba_node in AlbaNodeList.get_albanodes():
            try:
                alba_node.client.get_metadata()
            except Exception:
                alba_prerequisites.append(['alba_node_unresponsive', alba_node.ip])

        default_entry = {'packages': {},
                         'downtime': [],
                         'prerequisites': [],
                         'services_stop_start': {10: set(), 20: set()},  # Lowest get stopped first and started last
                         'services_post_update': {10: set(), 20: set()}}  # Lowest get restarted first

        #  Combine all information
        for storagerouter in StorageRouterList.get_storagerouters():
            # Retrieve ALBA proxy downtimes
            alba_proxy_downtime = []
            for service in storagerouter.services:
                if service.type.name != ServiceType.SERVICE_TYPES.ALBA_PROXY or service.alba_proxy is None:
                    continue
                alba_proxy_downtime.append(['proxy', service.alba_proxy.storagedriver.vpool.name])

            # Retrieve Arakoon downtimes
            arakoon_downtime = []
            for service in storagerouter.services:
                if service.type.name not in [ServiceType.SERVICE_TYPES.ALBA_MGR, ServiceType.SERVICE_TYPES.NS_MGR]:
                    continue

                if service.type.name == ServiceType.SERVICE_TYPES.ALBA_MGR:
                    cluster_name = service.abm_service.abm_cluster.name
                else:
                    cluster_name = service.nsm_service.nsm_cluster.name

                arakoon_info = ArakoonInstaller.get_arakoon_update_info(internal_cluster_name=cluster_name)
                if arakoon_info['downtime'] is True and arakoon_info['internal'] is True:
                    if service.type.name == ServiceType.SERVICE_TYPES.ALBA_MGR:
                        arakoon_downtime.append(['backend', service.abm_service.abm_cluster.alba_backend.name])
                    else:
                        arakoon_downtime.append(['backend', service.nsm_service.nsm_cluster.alba_backend.name])

            for component, package_names in PackageFactory.get_package_info()['names'].iteritems():
                if component not in storagerouter.package_information:
                    continue

                if component not in information:
                    information[component] = copy.deepcopy(default_entry)
                component_info = information[component]

                # Loop the actual update information
                for package_name, package_info in storagerouter.package_information[component].iteritems():
                    if package_name not in package_names:
                        continue  # Only gather the information for the packages related to the current component

                    # Add the services which require a restart to the post_update services
                    for importance, services in package_info.pop('services_to_restart', {}).iteritems():
                        if importance not in component_info['services_post_update']:
                            component_info['services_post_update'][importance] = set()
                        component_info['services_post_update'][importance].update(set(services))
                    # Add the version information for current package
                    if package_name not in component_info['packages']:
                        component_info['packages'][package_name] = package_info

                    # Add downtime and additional services for each package
                    if package_name == PackageFactory.PKG_OVS_BACKEND:
                        if ['gui', None] not in component_info['downtime']:
                            component_info['downtime'].append(['gui', None])
                        if ['api', None] not in component_info['downtime']:
                            component_info['downtime'].append(['api', None])
                        component_info['services_stop_start'][10].add('watcher-framework')
                        component_info['services_stop_start'][20].add('memcached')
                    elif package_name in [PackageFactory.PKG_ALBA, PackageFactory.PKG_ALBA_EE]:
                        for downtime in alba_proxy_downtime:
                            if downtime not in component_info['downtime']:
                                component_info['downtime'].append(downtime)
                        for downtime in arakoon_downtime:
                            if downtime not in component_info['downtime']:
                                component_info['downtime'].append(downtime)
                    elif package_name == PackageFactory.PKG_ARAKOON:
                        if component == PackageFactory.COMP_ALBA:
                            for downtime in arakoon_downtime:
                                if downtime not in component_info['downtime']:
                                    component_info['downtime'].append(downtime)

        for alba_node in AlbaNodeList.get_albanodes():
            for component, all_package_info in alba_node.package_information.iteritems():
                if component not in information:
                    information[component] = copy.deepcopy(default_entry)
                component_info = information[component]
                if component == PackageFactory.COMP_ALBA:
                    component_info['prerequisites'].extend(alba_prerequisites)

                for package_name, package_info in all_package_info.iteritems():
                    package_info.pop('services_to_restart', {})
                    if package_name not in component_info['packages']:
                        component_info['packages'][package_name] = package_info
        return information

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
    def _post_update_alba_plugin_framework(cls, client, components, update_information):
        """
        Execute functionality after the openvstorage-backend core packages have been updated
        For ALBA:
            * Restart ABM arakoons on every client (if present and required)
            * Restart NSM arakoons on every client (if present and required)
        :param client: Client on which to execute this post update functionality
        :type client: SSHClient
        :param components: Update components which have been executed
        :type components: list
        :param update_information: Information required for an update
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

        other_services = set()
        arakoon_services = set()
        for component, update_info in update_information.iteritems():
            if component not in PackageFactory.SUPPORTED_COMPONENTS:
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
                arakoon_metadata = ArakoonInstaller.get_arakoon_update_info(actual_cluster_name=cluster_name)
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
