# Copyright (C) 2017 iNuron NV
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
AlbaMigrationController module
"""

from ovs.extensions.generic.logger import Logger
from ovs.lib.helpers.decorators import ovs_task
from ovs.lib.helpers.toolbox import Schedule


class AlbaMigrationController(object):
    """
    This controller contains (part of the) migration code. It runs out-of-band with the updater so we reduce the risk of failures during the update
    """
    _logger = Logger(name='update', forced_target_type='file')

    @staticmethod
    @ovs_task(name='alba.migration.migrate', schedule=Schedule(minute='15', hour='6'), ensure_single_info={'mode': 'DEFAULT'})
    def migrate():
        """
        Executes async migrations. It doesn't matter too much when they are executed, as long as they get eventually
        executed. This code will typically contain:
        * "dangerous" migration code (it needs certain running services)
        * Migration code depending on a cluster-wide state
        * ...
        """
        AlbaMigrationController._logger.info('Preparing out of band migrations...')

        from ovs.dal.lists.albabackendlist import AlbaBackendList
        from ovs.dal.lists.albanodelist import AlbaNodeList
        from ovs.dal.lists.albaosdlist import AlbaOSDList
        from ovs.dal.lists.storagerouterlist import StorageRouterList
        from ovs.extensions.generic.configuration import Configuration
        from ovs.extensions.generic.sshclient import SSHClient, UnableToConnectException
        from ovs.extensions.packages.albapackagefactory import PackageFactory
        from ovs.extensions.services.albaservicefactory import ServiceFactory
        from ovs.extensions.plugins.albacli import AlbaCLI, AlbaError
        from ovs.lib.alba import AlbaController

        AlbaMigrationController._logger.info('Start out of band migrations...')

        #############################################
        # Introduction of IP:port combination on OSDs
        osd_info_map = {}
        alba_backends = AlbaBackendList.get_albabackends()
        for alba_backend in alba_backends:
            AlbaMigrationController._logger.info('Verifying ALBA Backend {0}'.format(alba_backend.name))
            if alba_backend.abm_cluster is None:
                AlbaMigrationController._logger.warning('ALBA Backend {0} does not have an ABM cluster registered'.format(alba_backend.name))
                continue

            AlbaMigrationController._logger.debug('Retrieving configuration path for ALBA Backend {0}'.format(alba_backend.name))
            try:
                config = Configuration.get_configuration_path(alba_backend.abm_cluster.config_location)
            except:
                AlbaMigrationController._logger.exception('Failed to retrieve the configuration path for ALBA Backend {0}'.format(alba_backend.name))
                continue

            AlbaMigrationController._logger.info('Retrieving OSD information for ALBA Backend {0}'.format(alba_backend.name))
            try:
                osd_info = AlbaCLI.run(command='list-all-osds', config=config)
            except (AlbaError, RuntimeError):
                AlbaMigrationController._logger.exception('Failed to retrieve OSD information for ALBA Backend {0}'.format(alba_backend.name))
                continue

            for osd_info in osd_info:
                if osd_info.get('long_id'):
                    osd_info_map[osd_info['long_id']] = {'ips': osd_info.get('ips', []),
                                                         'port': osd_info.get('port')}

        for osd in AlbaOSDList.get_albaosds():
            if osd.osd_id not in osd_info_map:
                AlbaMigrationController._logger.warning('OSD with ID {0} is modelled but could not be found through ALBA'.format(osd.osd_id))
                continue

            ips = osd_info_map[osd.osd_id]['ips']
            port = osd_info_map[osd.osd_id]['port']
            changes = False
            if osd.ips is None:
                changes = True
                osd.ips = ips
            if osd.port is None:
                changes = True
                osd.port = port
            if changes is True:
                AlbaMigrationController._logger.info('Updating OSD with ID {0} with IPS {1} and port {2}'.format(osd.osd_id, ips, port))
                osd.save()

        ###################################################
        # Read preference for GLOBAL ALBA Backends (1.10.3)  (https://github.com/openvstorage/framework-alba-plugin/issues/452)
        if Configuration.get(key='/ovs/framework/migration|read_preference', default=False) is False:
            try:
                name_backend_map = dict((alba_backend.name, alba_backend) for alba_backend in alba_backends)
                for alba_node in AlbaNodeList.get_albanodes():
                    AlbaMigrationController._logger.info('Processing maintenance services running on ALBA Node {0} with ID {1}'.format(alba_node.ip, alba_node.node_id))
                    alba_node.invalidate_dynamics('maintenance_services')
                    for alba_backend_name, services in alba_node.maintenance_services.iteritems():
                        if alba_backend_name not in name_backend_map:
                            AlbaMigrationController._logger.error('ALBA Node {0} has services for an ALBA Backend {1} which is not modelled'.format(alba_node.ip, alba_backend_name))
                            continue

                        alba_backend = name_backend_map[alba_backend_name]
                        AlbaMigrationController._logger.info('Processing {0} ALBA Backend {1} with GUID {2}'.format(alba_backend.scaling, alba_backend.name, alba_backend.guid))
                        if alba_backend.scaling == alba_backend.SCALINGS.LOCAL:
                            read_preferences = [alba_node.node_id]
                        else:
                            read_preferences = AlbaController.get_read_preferences_for_global_backend(alba_backend=alba_backend,
                                                                                                      alba_node_id=alba_node.node_id,
                                                                                                      read_preferences=[])

                        for service_name, _ in services:
                            AlbaMigrationController._logger.info('Processing service {0}'.format(service_name))
                            old_config_key = '/ovs/alba/backends/{0}/maintenance/config'.format(alba_backend.guid)
                            new_config_key = '/ovs/alba/backends/{0}/maintenance/{1}/config'.format(alba_backend.guid, service_name)
                            if Configuration.exists(key=old_config_key):
                                new_config = Configuration.get(key=old_config_key)
                                new_config['read_preference'] = read_preferences
                                Configuration.set(key=new_config_key, value=new_config)
                for alba_backend in alba_backends:
                    Configuration.delete(key='/ovs/alba/backends/{0}/maintenance/config'.format(alba_backend.guid))
                AlbaController.checkup_maintenance_agents.delay()

                Configuration.set(key='/ovs/framework/migration|read_preference', value=True)
            except Exception:
                AlbaMigrationController._logger.exception('Updating read preferences for ALBA Backends failed')

        #######################################################
        # Storing actual package name in version files (1.11.0) (https://github.com/openvstorage/framework/issues/1876)
        if Configuration.get(key='/ovs/framework/migration|actual_package_name_in_version_file_alba', default=False) is False:
            try:
                alba_pkg_name, _ = PackageFactory.get_package_and_version_cmd_for(component=PackageFactory.COMP_ALBA)
                for storagerouter in StorageRouterList.get_storagerouters():
                    try:
                        client = SSHClient(endpoint=storagerouter.ip, username='root')  # Use '.ip' instead of StorageRouter object because this code is executed during post-update at which point the heartbeat has not been updated for some time
                    except UnableToConnectException:
                        AlbaMigrationController._logger.exception('Updating actual package name for version files failed on StorageRouter {0}'.format(storagerouter.ip))
                        continue

                    for file_name in client.file_list(directory=ServiceFactory.RUN_FILE_DIR):
                        if not file_name.endswith('.version'):
                            continue
                        file_path = '{0}/{1}'.format(ServiceFactory.RUN_FILE_DIR, file_name)
                        contents = client.file_read(filename=file_path)
                        if alba_pkg_name == PackageFactory.PKG_ALBA_EE and '{0}='.format(PackageFactory.PKG_ALBA) in contents:
                            contents = contents.replace(PackageFactory.PKG_ALBA, PackageFactory.PKG_ALBA_EE)
                            client.file_write(filename=file_path, contents=contents)
                Configuration.set(key='/ovs/framework/migration|actual_package_name_in_version_file_alba', value=True)
            except Exception:
                AlbaMigrationController._logger.exception('Updating actual package name for version files failed')

        AlbaMigrationController._logger.info('Finished out of band migrations')

    @staticmethod
    @ovs_task(name='alba.migration.migrate_sdm', schedule=Schedule(minute='30', hour='6'), ensure_single_info={'mode': 'DEFAULT'})
    def migrate_sdm():
        """
        Executes async migrations for ALBA SDM node. It doesn't matter too much when they are executed, as long as they get eventually executed.
        This code will typically contain:
        * "dangerous" migration code (it needs certain running services)
        * Migration code depending on a cluster-wide state
        * ...
        """
        from ovs.dal.lists.albanodelist import AlbaNodeList

        AlbaMigrationController._logger.info('Preparing out of band migrations for SDM...')
        for alba_node in AlbaNodeList.get_albanodes():
            try:
                AlbaMigrationController._logger.info('Executing post-update migration code for ALBA Node {0}'.format(alba_node.node_id))
                alba_node.client.update_execute_migration_code()
            except Exception:
                AlbaMigrationController._logger.exception('Executing post-update migration code for ALBA Node {0} failed'.format(alba_node.node_id))
        AlbaMigrationController._logger.info('Finished out of band migrations for SDM')
