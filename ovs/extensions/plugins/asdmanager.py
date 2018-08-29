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
import time
import base64
import requests
from ovs.extensions.plugins.albabase import AlbaBaseClient
from ovs.extensions.generic.configuration import Configuration
from ovs_extensions.generic.exceptions import NotFoundError


class ASDManagerClient(AlbaBaseClient):
    """
    ASD Manager Client
    """

    def __init__(self, node, timeout=None):
        # type: (ovs.dal.hybrids.albanode.AlbaNode, int) -> None
        if timeout is None:
            timeout = Configuration.get('/ovs/alba/asdnodes/main|client_timeout', default=20)
        super(ASDManagerClient, self).__init__(node, timeout)

    def _refresh(self):
        # type: () -> Tuple[str, dict]
        """
        Refresh the endpoint and credentials
        This function is called before every request
        :return: The base URL and the 'Authorization' header
        :rtype: tuple
        """
        # The node data might have changed
        # @todo revisit. THe node is never reloaded so this wont ever change?
        base_url = 'https://{0}:{1}'.format(self.node.ip, self.node.port)
        base_headers = {'Authorization': 'Basic {0}'.format(base64.b64encode('{0}:{1}'.format(self.node.username, self.node.password)).strip())}
        return base_url, base_headers

    def get_metadata(self):
        # type: () -> dict
        """
        Gets metadata from the node
        """
        # Backward compatibility
        return self._call(requests.get, '')

    ##############
    # SLOTS/OSDS #
    ##############
    def get_stack(self):
        # type: () -> dict
        """
        Gets the remote node stack
        :return: stack data
        :rtype: dict
        """
        # Version 3 introduced 'slots'
        if self.get_metadata()['_version'] >= 3:
            data = self.extract_data(self._call(requests.get, 'slots', timeout=5))
            for slot_info in data.itervalues():
                for osd in slot_info.get('osds', {}).itervalues():
                    osd['type'] = 'ASD'
            return data

        # Version 2 and older used AlbaDisk
        data = self._call(method=requests.get, url='disks', timeout=5, clean=True)
        for disk_id, value in data.iteritems():
            if len(value.get('partition_aliases', [])) == 0:  # disks/<disk_id>/asds raises error if no partition_aliases could be found for current disk
                value[ur'osds'] = {}
                value[u'state'] = 'empty'
                continue

            value[u'osds'] = self._call(method=requests.get, url='disks/{0}/asds'.format(disk_id), clean=True)
            value[u'state'] = 'empty' if len(value['osds']) == 0 else 'ok'
            for osd_id, osd_info in value['osds'].iteritems():
                osd_info[u'ips'] = osd_info.get('ips', [])
                osd_info[u'type'] = 'ASD'
                osd_info[u'folder'] = osd_id
        return data

    def fill_slot(self, slot_id, extra, *args, **kwargs):
        # type: (str, dict, *any, **any) -> None
        """
        Fills a slot (disk) with one or more OSDs
        :param slot_id: Id of the slot to fill
        :param extra: Extra parameters to supply. Supported extra params: {count: number of asds to add}
        :type extra: dict
        :return: None
        :rtype: NoneType
        """
        # Call can raise a NotFoundException when the slot could no longer be found
        for _ in xrange(extra['count']):
            self._call(requests.post, 'slots/{0}/asds'.format(slot_id))

    def restart_osd(self, slot_id, osd_id, *args, **kwargs):
        # type: (str, str, *any, **any) -> None
        """
        Restarts a given OSD in a given Slot
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :param osd_id: Identifier of the OSD
        :type osd_id: str
        :return: None
        :rtype: NoneType
        """
        return self._call(requests.post, 'slots/{0}/asds/{1}/restart'.format(slot_id, osd_id))

    def update_osd(self, slot_id, osd_id, update_data):
        # type: (str, str, dict) -> None
        """
        Updates a given OSD in a given Slot
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :param osd_id: Identifier of the OSD
        :type osd_id: str
        :param update_data: Data to update the OSD with
        :type update_data: dict
        :return: None
        :rtype: NoneType
        """
        return self._call(method=requests.post,
                          url='slots/{0}/asds/{1}/update'.format(slot_id, osd_id),
                          data={'update_data': json.dumps(update_data)})

    def delete_osd(self, slot_id, osd_id, *args, **kwargs):
        # type: (str, str, *any, **any) -> None
        """
        Deletes the OSD from the Slot
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :param osd_id: Identifier of the OSD
        :type osd_id: str
        :return: None
        :rtype: NoneType
        """
        return self._call(requests.delete, 'slots/{0}/asds/{1}'.format(slot_id, osd_id))

    def build_slot_params(self, osd, *args, **kwargs):
        # type: (ovs.dal.hybrids.albaosd.AlbaOSD, *any, **any) -> dict
        """
        Builds the "extra" params for replacing an OSD
        :param osd: The OSD to generate the params for
        :type osd: ovs.dal.hybrids.albaosd.AlbaOSD
        :return: The extra param used in the create osd code
        :rtype: dict
        """
        _ = self, osd
        return {'count': 1}

    def clear_slot(self, slot_id, *args, **kwargs):
        # type: (str, *any, **any) -> None
        """
        Clears the slot
        :param slot_id: Identifier of the slot to clear
        :type slot_id: str
        :return: None
        :rtype: NoneType
        """
        return self._call(requests.delete, 'slots/{0}'.format(slot_id))

    def restart_slot(self, slot_id, *args, **kwargs):
        # type: (str, *any, **any) -> None
        """
        Restart the slot with given slot id
        :param slot_id: Identifier of the slot to clear
        :type slot_id: str
        :return: None
        :rtype: NoneType
        """
        return self._call(requests.post, 'slots/{0}/restart'.format(slot_id))

    def stop_slot(self, slot_id, *args, **kwargs):
        # type: (str, *any, **any) -> None
        """
        Stops all OSDs on the slot
        :param slot_id: Identifier of the slot to clear
        :type slot_id: str
        :return: None
        :rtype: NoneType
        """
        return self._call(requests.post, 'slots/{0}/stop'.format(slot_id))

    ##########
    # UPDATE #
    ##########
    def get_package_information(self):
        # type: () -> dict
        """
        Retrieve the package information for this ALBA node
        :return: Latest available version and services which require a restart
        :rtype: dict
        """
        # For backwards compatibility we first attempt to retrieve using the newest API
        try:
            # Newest ASD Manager wraps it. Older ones require cleaning
            return self.extract_data(self._call(requests.get, 'update/package_information', timeout=120))
        except NotFoundError:
            update_info = self._call(requests.get, 'update/information', timeout=120, clean=True)
            if update_info['version']:
                return {'alba': {'openvstorage-sdm': {'candidate': update_info['version'],
                                                      'installed': update_info['installed'],
                                                      'services_to_restart': []}}}
            return {}

    def execute_update(self, package_name):
        # type: (str) -> None
        """
        Execute an update
        :param package_name: Package to update
        :return: None
        :rtype: NoneType
        """
        try:
            return self._call(requests.post, 'update/install/{0}'.format(package_name), timeout=300)
        except NotFoundError:
            # Backwards compatibility
            status = self._call(requests.post, 'update/execute/started', timeout=300).get('status', 'done')
            if status != 'done':
                counter = 0
                max_counter = 12
                while counter < max_counter:
                    status = self._call(requests.post, 'update/execute/{0}'.format(status), timeout=300).get('status', 'done')
                    if status == 'done':
                        break
                    time.sleep(10)
                    counter += 1
                if counter == max_counter:
                    raise Exception('Failed to update SDM')

    def update_execute_migration_code(self):
        # type: () -> None
        """
        Run some migration code after an update has been done
        :return: None
        :rtype: NoneType
        """
        return self._call(requests.post, 'update/execute_migration_code')

    def update_installed_version_package(self, package_name):
        # type: (str) -> str
        """
        Retrieve the currently installed package version
        :param package_name: Name of the package to retrieve the version for
        :type package_name: str
        :return: Version of the currently installed package
        :rtype: str
        """
        return self.extract_data(self._call(requests.get, 'update/installed_version_package/{0}'.format(package_name), timeout=60),
                                 old_key='version')

    ############
    # SERVICES #
    ############
    def restart_services(self, service_names=None):
        # type: (Optional[str]) -> None
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
        # type: (str, str, str, List[str]) -> dict
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
        :rtype: dict
        """
        return self._call(method=requests.post,
                          url='maintenance/{0}/add'.format(name),
                          data={'abm_name': abm_name,
                                'read_preferences': json.dumps(read_preferences),
                                'alba_backend_guid': alba_backend_guid})

    def remove_maintenance_service(self, name, alba_backend_guid):
        # type: (str, str) -> dict
        """
        Remove service from asd manager
        :param name: Name of the maintenance service to remove
        :type name: str
        :param alba_backend_guid: Guid of the ALBA Backend to which the maintenance service belongs
        :type alba_backend_guid: str
        :return: result
        :rtype: dict
        """
        return self._call(method=requests.post,
                          url='maintenance/{0}/remove'.format(name),
                          data={'alba_backend_guid': alba_backend_guid})

    def list_maintenance_services(self):
        # type: () -> dict
        """
        Retrieve configured maintenance services from asd manager
        :return: dict of services
        :rtype: dict
        """
        return self.extract_data(self._call(requests.get, 'maintenance', clean=True),
                                 old_key='services')

    def get_service_status(self, name):
        # type: (str) -> str
        """
        Retrieve the status of the service specified
        :param name: Name of the service to check
        :type name: str
        :return: Status of the service
        :rtype: str
        """
        return self.extract_data(self._call(requests.get, 'service_status/{0}'.format(name)),
                                 old_key='status')[1]

    def sync_stack(self, stack, *args, **kwargs):
        # type: (dict, *any, **any) -> None
        """
        Synchronize the stack of an AlbaNode with the stack of another AlbaNode
        :param stack: Stack to sync
        :return: None
        :rtype: Nonetype
        """
        return self._call(requests.post, 'dual_controller/sync_stack', data={'stack': json.dumps(stack)})

    @classmethod
    def clean(cls, data):
        # type: (dict) -> dict
        """
        Clean data of metadata keys
        :param data: Dict with data
        :type data: dict
        :return: Cleaned data
        :rtype: dict
        """
        data_copy = data.copy()
        for key in data.iterkeys():
            if key.startswith('_'):
                del data_copy[key]
            elif isinstance(data_copy[key], dict):
                data_copy[key] = cls.clean(data_copy[key])
        return data_copy
