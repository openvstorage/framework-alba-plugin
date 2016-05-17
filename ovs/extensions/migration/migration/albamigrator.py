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

from ovs.log.logHandler import LogHandler


class AlbaMigrator(object):
    """
    Handles all model related migrations
    """

    identifier = 'alba'  # Used by migrator.py, so don't remove

    def __init__(self):
        """ Init method """
        pass

    @staticmethod
    def migrate(previous_version, master_ips=None, extra_ips=None):
        """
        Migrates from any version to any version, running all migrations required
        If previous_version is for example 0 and this script is at
        verison 3 it will execute two steps:
          - 1 > 2
          - 2 > 3
        :param previous_version: The previous version from which to start the migration.
        :param master_ips: IP addresses of the MASTER nodes
        :param extra_ips: IP addresses of the EXTRA nodes
        """
        logger = LogHandler.get('extensions', name='albamigration')
        working_version = previous_version

        # Version 1 introduced:
        # - Etcd
        if working_version < 1:
            try:
                import os
                import json
                from ovs.extensions.db.etcd import installer
                reload(installer)
                from ovs.extensions.db.etcd.installer import EtcdInstaller
                from ovs.extensions.db.etcd.configuration import EtcdConfiguration
                from ovs.extensions.generic.system import System
                host_id = System.get_my_machine_id()
                etcd_migrate = False
                if EtcdInstaller.has_cluster('127.0.0.1', 'config'):
                    etcd_migrate = True
                else:
                    if master_ips is not None and extra_ips is not None:
                        cluster_ip = None
                        for ip in master_ips + extra_ips:
                            if EtcdInstaller.has_cluster(ip, 'config'):
                                cluster_ip = ip
                                break
                        node_ip = None
                        path = '/opt/OpenvStorage/config/ovs.json'
                        if os.path.exists(path):
                            with open(path) as config_file:
                                config = json.load(config_file)
                                node_ip = config['grid']['ip']
                        if node_ip is not None:
                            if cluster_ip is None:
                                EtcdInstaller.create_cluster('config', node_ip)
                                EtcdConfiguration.initialize()
                                EtcdConfiguration.initialize_host(host_id)
                            else:
                                EtcdInstaller.extend_cluster(cluster_ip, node_ip, 'config')
                                EtcdConfiguration.initialize_host(host_id)
                            etcd_migrate = True
                if etcd_migrate is True:
                    # At this point, there is an etcd cluster. Migrating alba.json
                    path = '/opt/OpenvStorage/config/alba.json'
                    if os.path.exists(path):
                        with open(path) as config_file:
                            config = json.load(config_file)
                            EtcdConfiguration.set('/ovs/framework/plugins/alba/config', config)
                        os.remove(path)
                        EtcdConfiguration.set('/ovs/alba/backends/global_gui_error_interval', 300)
            except:
                logger.exception('Error migrating to version 1')

            working_version = 1

        return working_version
