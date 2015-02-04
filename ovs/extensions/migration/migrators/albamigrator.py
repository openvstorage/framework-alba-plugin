# Copyright 2014 CloudFounders NV
# All rights reserved

"""
ALBA migration module
"""

from ovs.dal.hybrids.backendtype import BackendType
from ovs.dal.hybrids.servicetype import ServiceType


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
        verison 3 it will execute two steps:
          - 1 > 2
          - 2 > 3
        @param previous_version: The previous version from which to start the migration.
        """

        working_version = previous_version

        # Version 0.0.1 introduced:
        if working_version < 1:
            # Add backends
            for backend_type_info in [('ALBA', 'alba')]:
                backend_type = BackendType()
                backend_type.name = backend_type_info[0]
                backend_type.code = backend_type_info[1]
                backend_type.save()

            # Add service types
            for service_type_info in ['NamespaceManager', 'AlbaManager']:
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
