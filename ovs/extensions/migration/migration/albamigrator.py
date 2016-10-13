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


class AlbaMigrator(object):
    """
    Handles all model related migrations
    """

    identifier = 'alba'  # Used by migrator.py, so don't remove
    THIS_VERSION = 11

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
            # Complete rework of the way we detect devices to assign roles or use as ASD
            # Allow loop-, raid-, nvme-, ??-devices and logical volumes as ASD (https://github.com/openvstorage/framework/issues/792)
            from ovs.dal.lists.albanodelist import AlbaNodeList

            for alba_node in AlbaNodeList.get_albanodes():
                all_disks = alba_node.client.get_disks()
                for alba_disk in alba_node.disks:
                    for disk_info in all_disks.itervalues():
                        if '/dev/disk/by-id/{0}'.format(alba_disk.name) in disk_info['aliases']:
                            alba_disk.aliases = disk_info['aliases']
                            alba_disk.save()
                            break

        return AlbaMigrator.THIS_VERSION
