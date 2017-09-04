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
    _logger = Logger('lib')

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
        from ovs.dal.lists.albaosdlist import AlbaOSDList
        from ovs.extensions.generic.configuration import Configuration
        from ovs.extensions.plugins.albacli import AlbaCLI, AlbaError

        AlbaMigrationController._logger.info('Start out of band migrations...')

        osd_info_map = {}
        for alba_backend in AlbaBackendList.get_albabackends():
            AlbaMigrationController._logger.debug('Verifying ALBA Backend {0}'.format(alba_backend.name))
            if alba_backend.abm_cluster is None:
                AlbaMigrationController._logger.warning('ALBA Backend {0} does not have an ABM cluster registered'.format(alba_backend.name))
                continue

            AlbaMigrationController._logger.debug('Retrieving configuration path for ALBA Backend {0}'.format(alba_backend.name))
            try:
                config = Configuration.get_configuration_path(alba_backend.abm_cluster.config_location)
            except:
                AlbaMigrationController._logger.exception('Failed to retrieve the configuration path for ALBA Backend {0}'.format(alba_backend.name))
                continue

            AlbaMigrationController._logger.debug('Retrieving OSD information for ALBA Backend {0}'.format(alba_backend.name))
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
                AlbaMigrationController._logger.debug('Updating OSD with ID {0} with IPS {1} and port {2}'.format(osd.osd_id, ips, port))
                osd.save()

        AlbaMigrationController._logger.info('Finished out of band migrations')
