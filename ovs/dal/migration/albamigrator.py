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
ALBA migration module
"""

from ovs.dal.hybrids.backendtype import BackendType
from ovs.dal.hybrids.servicetype import ServiceType
from ovs.dal.lists.backendtypelist import BackendTypeList


class ALBAMigrator(object):
    """
    Handles all model related migrations
    """

    identifier = 'alba'

    def __init__(self):
        """ Init method """
        pass

    @staticmethod
    def migrate(previous_version):
        """
        Migrates from any version to any version, running all migrations required
        If previous_version is for example 0 and this script is at
        version 3 it will execute two steps:
          - 1 > 2
          - 2 > 3
        @param previous_version: The previous version from which to start the migration.
        """

        working_version = previous_version

        # Version 0.0.1 introduced:
        if working_version < 1:
            # Add backends
            for backend_type_info in [('ALBA', 'alba')]:
                code = backend_type_info[1]
                backend_type = BackendTypeList.get_backend_type_by_code(code)
                if backend_type is None:
                    backend_type = BackendType()
                backend_type.name = backend_type_info[0]
                backend_type.code = code
                backend_type.save()

            # Add service types
            for service_type_info in [ServiceType.SERVICE_TYPES.NS_MGR, ServiceType.SERVICE_TYPES.ALBA_MGR]:
                service_type = ServiceType()
                service_type.name = service_type_info
                service_type.save()

            # We're now at version 0.0.1
            working_version = 1

        # Version 0.0.2 introduced:
        if working_version < 2:
            # Execute some code that upgrades to version 2
            # working_version = 2
            pass

        return working_version
