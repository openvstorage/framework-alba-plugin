# Copyright 2014 iNuron NV
#
# Licensed under the Open vStorage Modified Apache License (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.openvstorage.org/license
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
                code = backend_type_info[1]
                backend_type = BackendTypeList.get_backend_type_by_code(code)
                if backend_type is None:
                    backend_type = BackendType()
                backend_type.name = backend_type_info[0]
                backend_type.code = code
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
