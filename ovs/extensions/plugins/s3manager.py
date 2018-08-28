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
Generic module for calling the ASD-Manager
"""

import json
import requests
from ovs.extensions.plugins.albabase import AlbaBaseClient


class S3ManagerClient(AlbaBaseClient):
    """
    ASD Manager Client
    """
    def __init__(self, node, timeout=None):
        # type: (ovs.dal.hybrids.albanode.AlbaNode, int) -> None
        super(S3ManagerClient, self).__init__(node, timeout)

    def get_metadata(self):
        """
        Gets metadata from the node
        """
        return self._call(requests.get, '')

    ##############
    # SLOTS/OSDS #
    ##############
    def get_stack(self):
        """
        Gets the remote node stack
        """
        data = self._call(requests.get, 'slots', timeout=5, clean=True)
        for slot_info in data.itervalues():
            for osd in slot_info.get('osds', {}).itervalues():
                osd['type'] = 'S3'
        return data

    def fill_slot(self, slot_id, extra):
        """
        Fills a slot (disk) with one or more OSDs
        :param slot_id: Id of the slot to fill
        :param extra: Extra parameters to supply. Supported extra params: {count: number of asds to add}
        :type extra: dict
        """
        # Call can raise a NotFoundException when the slot could no longer be found
        for _ in xrange(extra['count']):
            self._call(requests.post, 'slots/{0}/osds'.format(slot_id))

    def restart_osd(self, slot_id, osd_id):
        """
        Restarts a given OSD in a given Slot
        """
        return self._call(requests.post, 'slots/{0}/osds/{1}/restart'.format(slot_id, osd_id))

    def update_osd(self, slot_id, osd_id, update_data):
        """
        Updates a given OSD in a given Slot
        """
        return self._call(method=requests.post,
                          url='slots/{0}/osds/{1}/update'.format(slot_id, osd_id),
                          data={'update_data': json.dumps(update_data)})

    def delete_osd(self, slot_id, osd_id):
        """
        Deletes the OSD from the Slot
        """
        return self._call(requests.delete, 'slots/{0}/osds/{1}'.format(slot_id, osd_id))

    def build_slot_params(self, osd):
        """
        Builds the "extra" params for replacing an OSD
        """
        _ = self, osd
        return {'count': 1}

    def clear_slot(self, slot_id):
        """
        Clears the slot
        """
        return self._call(requests.delete, 'slots/{0}'.format(slot_id))

    def restart_slot(self, slot_id):
        """
        Restart the slot with given slot id
        """
        return self._call(requests.post, 'slots/{0}/restart'.format(slot_id))

    def stop_slot(self, slot_id):
        """
        Stops all OSDs on the slot
        """
        return self._call(requests.post, 'slots/{0}/stop'.format(slot_id))

    ##########
    # UPDATE #
    ##########
    def get_package_information(self):
        """
        Retrieve the package information for this ALBA node
        :return: Latest available version and services which require a restart
        """
        return self._call(requests.get, 'update/package_information', timeout=120, clean=True)

    def execute_update(self, package_name):
        """
        Execute an update
        :return: None
        """
        return self._call(requests.post, 'update/install/{0}'.format(package_name), timeout=300)

    def update_execute_migration_code(self):
        """
        Run some migration code after an update has been done
        :return: None
        :rtype: NoneType
        """
        return self._call(requests.post, 'update/execute_migration_code')

    def update_installed_version_package(self, package_name):
        """
        Retrieve the currently installed package version
        :param package_name: Name of the package to retrieve the version for
        :type package_name: str
        :return: Version of the currently installed package
        :rtype: str
        """
        return self._call(requests.get, 'update/installed_version_package/{0}'.format(package_name), timeout=60)['version']

    ############
    # SERVICES #
    ############
    def restart_services(self, service_names=None):
        """
        Restart the specified services (alba-asd and maintenance services)
        :param service_names: Names of the services to restart
        :type service_names: list[str]
        :return: None
        :rtype: NoneType
        """
        if service_names is None:
            service_names = []
        return self._call(method=requests.post,
                          url='update/restart_services',
                          data={'service_names': json.dumps(service_names)})

    def add_maintenance_service(self, name, alba_backend_guid, abm_name, read_preferences):
        """
        Add service to asd manager
        :param name: Name of the service to add
        :type name: str
        :param alba_backend_guid: ALBA Backend GUID for which the maintenance service needs to run
        :type alba_backend_guid: str
        :param abm_name: The name of the ABM cluster
        :type abm_name: str
        :param read_preferences: List of ALBA Node IDs (LOCAL) or linked ALBA Backend Guids (GLOBAL) for the maintenance services where they should prioritize the READ actions
        :type read_preferences: list[str]
        :return: result
        """
        return self._call(method=requests.post,
                          url='maintenance/{0}/add'.format(name),
                          data={'abm_name': abm_name,
                                'read_preferences': json.dumps(read_preferences),
                                'alba_backend_guid': alba_backend_guid})

    def remove_maintenance_service(self, name, alba_backend_guid):
        """
        Remove service from asd manager
        :param name: Name of the maintenance service to remove
        :type name: str
        :param alba_backend_guid: Guid of the ALBA Backend to which the maintenance service belongs
        :type alba_backend_guid: str
        :return: result
        """
        return self._call(method=requests.post,
                          url='maintenance/{0}/remove'.format(name),
                          data={'alba_backend_guid': alba_backend_guid})

    def list_maintenance_services(self):
        """
        Retrieve configured maintenance services from asd manager
        :return: dict of services
        """
        return self._call(requests.get, 'maintenance', clean=True)['services']

    def get_service_status(self, name):
        """
        Retrieve the status of the service specified
        :param name: Name of the service to check
        :type name: str
        :return: Status of the service
        :rtype: str
        """
        return self._call(requests.get, 'service_status/{0}'.format(name))['status'][1]

    def sync_stack(self, stack):
        """
        Synchronize the stack of an AlbaNode with the stack of another AlbaNode
        :param stack: Stack to sync
        :return: None
        :rtype: Nonetype
        """
        raise NotImplementedError()
