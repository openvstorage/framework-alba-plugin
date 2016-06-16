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
        Migrates from a given version to the current version. It uses previous_version to be smart
        wherever possible, but the code should be able migrate any version towards the expected version.
        When this is not possible, the code can set a minimum version and raise when it is not met.
        :param previous_version: The previous version from which to start the migration.
        :type previous_version: float
        """

        working_version = previous_version

        if working_version == 0:
            # Initial version:
            # * Set the version to THIS RELEASE version
            #   Version  9: Fargo Alpha, Beta, RC
            #   Version 10: Fargo RTM
            # * Add any basic configuration or model entries

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

            return 9

        # From here on, all actual migration should happen to get to the expected state for THIS RELEASE
        if working_version < 10:
            raise RuntimeError('Cannot upgrade to Fargo')

        return working_version
