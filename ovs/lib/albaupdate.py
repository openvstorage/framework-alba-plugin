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
import logging
import requests
from ovs.constants.logging import UPDATE_LOGGER
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.hybrids.servicetype import ServiceType
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs.dal.migration.albamigrator import DALMigrator
from ovs.extensions.db.arakooninstaller import ArakoonInstaller
from ovs.extensions.generic.configuration import Configuration
from ovs_extensions.generic.remote import remote
from ovs.extensions.generic.system import System
from ovs_extensions.generic.toolbox import ExtensionsToolbox
from ovs.extensions.migration.migration.albamigrator import ExtensionMigrator
from ovs.extensions.packages.albapackagefactory import PackageFactory
from ovs.extensions.services.albaservicefactory import ServiceFactory
from ovs.extensions.storage.persistentfactory import PersistentFactory
from ovs.lib.alba import AlbaController
from ovs.lib.generic import GenericController
from ovs.lib.helpers.decorators import add_hooks


class AlbaUpdateController(object):
    """
    This class contains all logic for updating an environment
    """
    _logger = logging.getLogger(UPDATE_LOGGER)
    _package_manager = PackageFactory.get_manager()
    _service_manager = ServiceFactory.get_manager()

    #########
    # HOOKS #
    #########
    @classmethod
    @add_hooks('update', 'get_package_info_cluster')
    def _get_package_information_cluster_alba(cls, client, package_info):
        packages = PackageFactory.get_version_information(client)[0]

        try:
            for component, pkg_info in packages.iteritems():
                if component not in package_info[client.ip]:
                    package_info[client.ip][component] = pkg_info
                else:
                    for package_name, package_versions in pkg_info.iteritems():
                        package_info[client.ip][component][package_name] = package_versions
            cls._logger.info('StorageRouter {0}: Refreshed iSCSI package information'.format(client.ip))
        except Exception as ex:
            cls._logger.exception('StorageRouter {0}: Refreshing iSCSI package information failed'.format(client.ip))
            if 'errors' not in package_info[client.ip]:
                package_info[client.ip]['errors'] = []
            package_info[client.ip]['errors'].append(ex)

    @classmethod
    @add_hooks('update', 'get_package_update_info_cluster')
    def _get_package_update_information_cluster_iscsi(cls, client, package_info):
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
        Whether a service has the correct binary version in use, we use the ServiceFactory.get_service_update_versions functionality
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
                                service_version = ServiceFactory.get_service_update_versions(client=client, service_name=service.name, binary_versions=binaries)

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
                            service_version = ServiceFactory.get_service_update_versions(client=client, service_name=service_name, binary_versions=binaries, package_name=package_name)
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

                # Verify whether migration (DAL and extension) code needs to be executed (only if no packages have an update available so far)
                elif component == PackageFactory.COMP_FWK and PackageFactory.PKG_OVS_BACKEND not in svc_component_info['packages']:
                    cls._logger.debug('StorageRouter {0}: No updates detected, checking for required migrations'.format(client.ip))
                    # Extension migration check
                    key = '/ovs/framework/hosts/{0}/versions'.format(System.get_my_machine_id(client=client))
                    old_version = Configuration.get(key, default={}).get(PackageFactory.COMP_MIGRATION_ALBA)
                    installed_version = str(cls._package_manager.get_installed_versions(client=client, package_names=[PackageFactory.PKG_OVS_BACKEND])[PackageFactory.PKG_OVS_BACKEND])
                    migrations_detected = False
                    if old_version is not None:
                        cls._logger.debug('StorageRouter {0}: Current running version for {1} extension migrations: {2}'.format(client.ip, PackageFactory.COMP_ALBA, old_version))
                        with remote(client.ip, [ExtensionMigrator]) as rem:
                            cls._logger.debug('StorageRouter {0}: Available version for {1} extension migrations: {2}'.format(client.ip, PackageFactory.COMP_ALBA, rem.ExtensionMigrator.THIS_VERSION))
                            if rem.ExtensionMigrator.THIS_VERSION > old_version:
                                migrations_detected = True
                                svc_component_info['packages'][PackageFactory.PKG_OVS_BACKEND] = {'installed': 'migrations',
                                                                                                  'candidate': installed_version}

                    # DAL migration check
                    if migrations_detected is False:
                        persistent_client = PersistentFactory.get_client()
                        old_version = persistent_client.get('ovs_model_version').get(PackageFactory.COMP_MIGRATION_ALBA) if persistent_client.exists('ovs_model_version') else None
                        if old_version is not None:
                            cls._logger.debug('StorageRouter {0}: Current running version for {1} DAL migrations: {2}'.format(client.ip, PackageFactory.COMP_ALBA, old_version))
                            with remote(client.ip, [DALMigrator]) as rem:
                                cls._logger.debug('StorageRouter {0}: Available version for {1} DAL migrations: {2}'.format(client.ip, PackageFactory.COMP_ALBA, rem.DALMigrator.THIS_VERSION))
                                if rem.DALMigrator.THIS_VERSION > old_version:
                                    svc_component_info['packages'][PackageFactory.PKG_OVS_BACKEND] = {'installed': 'migrations',
                                                                                                      'candidate': installed_version}

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
                cls._logger.debug('ALBA Node {0}: Refreshed update information'.format(alba_node.ip))
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
    @add_hooks('update', 'package_install_plugin')
    def _package_install_plugin_alba(cls, components=None):
        """
        Update the packages related to the ASD manager
        :param components: Components which have been selected for update
        :type components: list
        :return: Boolean indicating whether to continue with the update or not
        :rtype: bool
        """
        cls._logger.info('Updating packages for ALBA plugin')
        if components is None:
            components = [PackageFactory.COMP_ALBA]

        abort = False
        alba_nodes = sorted(AlbaNodeList.get_albanodes_by_type(AlbaNode.NODE_TYPES.ASD),
                            key=lambda an: ExtensionsToolbox.advanced_sort(element=an.ip, separator='.'))
        for alba_node in alba_nodes:
            cls._logger.debug('ALBA Node {0}: Verifying packages'.format(alba_node.ip))
            for component in components:
                packages = alba_node.package_information.get(component, {}).get('packages', {})
                package_names = sorted(packages)
                # Always install the extensions package first
                if PackageFactory.PKG_OVS_EXTENSIONS in package_names:
                    package_names.remove(PackageFactory.PKG_OVS_EXTENSIONS)
                    package_names.insert(0, PackageFactory.PKG_OVS_EXTENSIONS)

                if len(package_names) > 0:
                    cls._logger.debug('ALBA Node {0}: Packages for component {1}: {2}'.format(alba_node.ip, component, package_names))
                for package_name in package_names:
                    try:
                        installed = packages[package_name]['installed']
                        candidate = packages[package_name]['candidate']

                        if candidate == alba_node.client.update_installed_version_package(package_name=package_name):
                            # Package has already been installed by another hook
                            continue

                        cls._logger.debug('ALBA Node {0}: Updating package {1} ({2} --> {3})'.format(alba_node.ip, package_name, installed, candidate))
                        alba_node.client.execute_update(package_name)
                        cls._logger.debug('ALBA Node {0}: Updated package {1}'.format(alba_node.ip, package_name))
                    except requests.ConnectionError as ce:
                        if 'Connection aborted.' not in ce.message:  # This error is thrown due the post-update code of the SDM package which restarts the asd-manager service
                            cls._logger.exception('ALBA Node {0}: Failed to update package {1}'.format(alba_node.ip, package_name))
                            abort = True
                    except Exception:
                        cls._logger.exception('ALBA Node {0}: Failed to update package {1}'.format(alba_node.ip, package_name))
                        abort = True

        if abort is False:
            cls._logger.info('Updated packages for ALBA plugin')
        return abort

    @classmethod
    @add_hooks('update', 'post_update_single')
    def _post_update_alba_plugin_alba(cls, components):
        """
        Execute some functionality after the ALBA plugin packages have been updated for the ASD manager nodes
        :param components: Update components which have been executed
        :type components: list
        :return: None
        :rtype: NoneType
        """
        if PackageFactory.COMP_ALBA not in components:
            return

        # First run post-update migrations to update services, config mgmt, ... and restart services afterwards
        for method_name in ['migrate', 'migrate_sdm']:
            try:
                # noinspection PyUnresolvedReferences
                from ovs.lib.albamigration import AlbaMigrationController
                cls._logger.debug('Executing migration code: AlbaMigrationController.{0}()'.format(method_name))
                getattr(AlbaMigrationController, method_name)()
            except ImportError:
                cls._logger.error('Could not import AlbaMigrationController')
            except Exception:
                cls._logger.exception('Migration code for the ALBA plugin failed to be executed')

        # Update ALBA nodes
        method_name = inspect.currentframe().f_code.co_name
        cls._logger.info('Executing hook {0}'.format(method_name))
        alba_nodes = sorted(AlbaNodeList.get_albanodes_by_type(AlbaNode.NODE_TYPES.ASD),
                            key=lambda an: ExtensionsToolbox.advanced_sort(element=an.ip, separator='.'))
        for alba_node in alba_nodes:
            services_to_restart = []
            for component in components:
                if component not in alba_node.package_information:
                    continue

                component_info = alba_node.package_information[component]
                if 'services_post_update' not in component_info:
                    # Package_information still has the old format, so refresh update information
                    # This can occur when updating from earlier than 2.11.0 to 2.11.0 and older
                    try:
                        GenericController.refresh_package_information()
                    except:
                        cls._logger.exception('{0}: Refreshing package information failed'.format(alba_node.ip))
                    alba_node.discard()
                    component_info = alba_node.package_information.get(component, {})

                services_post_update = dict((int(key), value) for key, value in component_info.get('services_post_update', {}).iteritems())
                for restart_order in sorted(services_post_update):
                    for service_name in sorted(services_post_update[restart_order]):
                        if service_name not in services_to_restart:
                            services_to_restart.append(service_name)

            if len(services_to_restart) > 0:
                alba_node.client.restart_services(service_names=services_to_restart)

        # Renew maintenance services
        cls._logger.info('Checkup maintenance agents')
        AlbaController.checkup_maintenance_agents.delay()

        cls._logger.info('Executed hook {0}'.format(method_name))

