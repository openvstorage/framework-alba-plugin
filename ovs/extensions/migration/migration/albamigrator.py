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
Alba migration module
"""

from ovs.extensions.generic.logger import Logger


class AlbaMigrator(object):
    """
    Handles all model related migrations
    """

    identifier = 'alba'  # Used by migrator.py, so don't remove
    THIS_VERSION = 12

    _logger = Logger('extensions')

    def __init__(self):
        """ Init method """
        pass

    @staticmethod
    def migrate(previous_version, master_ips=None, extra_ips=None):
        """
        Migrates from a given version to the current version. It uses 'previous_version' to be smart
        wherever possible, but the code should be able to migrate any version towards the expected version.
        When this is not possible, the code can set a minimum version and raise when it is not met.
        :param previous_version: The previous version from which to start the migration
        :type previous_version: float
        :param master_ips: IP addresses of the MASTER nodes
        :type master_ips: list or None
        :param extra_ips: IP addresses of the EXTRA nodes
        :type extra_ips: list or None
        """
        _ = master_ips, extra_ips
        working_version = previous_version

        # From here on, all actual migration should happen to get to the expected state for THIS RELEASE
        if working_version < AlbaMigrator.THIS_VERSION:
            try:
                from ovs.dal.lists.albabackendlist import AlbaBackendList
                from ovs.extensions.generic.configuration import Configuration, NotFoundException
                from ovs.lib.alba import AlbaController

                AlbaMigrator._logger.info('Starting migrations...')

                # This could be handled by out of band migrations, but since post-update restarts the services,
                # putting this in the out of band migration code would result in the services being restarted before
                # having updated this setting (See wrong order)
                # Correct order: This migration code --> Post-update code --> Restart services
                # Wrong order  : Post-update code --> Restart services --> Out of band migration making changes to configuration
                for alba_backend in AlbaBackendList.get_albabackends():
                    config_key = '{0}/maintenance/config'.format(AlbaController.CONFIG_ALBA_BACKEND_KEY.format(alba_backend.guid))
                    if Configuration.exists(key=config_key):
                        config = Configuration.get(key=config_key)
                        if 'multicast_discover_osds' not in config:
                            config['multicast_discover_osds'] = False
                            Configuration.set(key=config_key, value=config)
                            AlbaMigrator._logger.info('Updated multi-cast setting for ALBA Backend {0}'.format(alba_backend.name))
                AlbaMigrator._logger.info('Finished migrations')

                if not Configuration.exists(key='/ovs/alba/logging'):
                    try:
                        current_logging = Configuration.get(key='/ovs/framework/logging')
                    except (IOError, NotFoundException):
                        current_logging = {'type': 'console', 'level': 'info'}

                    Configuration.set(key='/ovs/alba/logging', value=current_logging)

            except:
                AlbaMigrator._logger.exception('Error occurred while executing the ALBA migration code')
                # Don't update migration version with latest version, resulting in next migration trying again to execute this code
                return AlbaMigrator.THIS_VERSION - 1

        return AlbaMigrator.THIS_VERSION
