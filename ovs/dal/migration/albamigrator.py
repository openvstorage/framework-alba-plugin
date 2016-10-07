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
    THIS_VERSION = 10

    def __init__(self):
        """ Init method """
        pass

    @staticmethod
    def migrate(previous_version):
        """
        Migrates from a given version to the current version. It uses 'previous_version' to be smart
        wherever possible, but the code should be able to migrate any version towards the expected version.
        When this is not possible, the code can set a minimum version and raise when it is not met.
        :param previous_version: The previous version from which to start the migration
        :type previous_version: float
        """

        working_version = previous_version

        if working_version == 0:
            # Initial version:
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

        # From here on, all actual migration should happen to get to the expected state for THIS RELEASE
        elif working_version < ALBAMigrator.THIS_VERSION:
            # Migrate unique constraints
            import hashlib
            from ovs.dal.helpers import HybridRunner, Descriptor
            from ovs.extensions.storage.persistentfactory import PersistentFactory
            client = PersistentFactory.get_client()
            hybrid_structure = HybridRunner.get_hybrids()
            for class_descriptor in hybrid_structure.values():
                cls = Descriptor().load(class_descriptor).get_object()
                classname = cls.__name__.lower()
                uniques = []
                for prop in cls._properties:
                    if prop.unique is True:
                        uniques.append(prop.name)
                if len(uniques) > 0:
                    unique_key = 'ovs_unique_{0}_{{0}}_'.format(classname)
                    for property_name in uniques[:]:
                        if len([k for k in client.prefix(unique_key.format(property_name))]) > 0:
                            uniques.remove(property_name)
                    if len(uniques) > 0:
                        prefix = 'ovs_data_{0}_'.format(classname)
                        for key in client.prefix(prefix):
                            data = client.get(key)
                            for property_name in uniques:
                                key = '{0}{1}'.format(unique_key.format(property_name), hashlib.sha1(str(data[property_name])).hexdigest())
                                client.set(key, 0)

        return ALBAMigrator.THIS_VERSION
