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


class OSDParams(object):
    """
    Parameters to provide when creating a new OSD
    """
    def __init__(self, count, transaction_arakoon_url, buckets, *args, **kwargs):
        # type: (int, str, List[str], *any, **any) -> None
        """
        Initialize new params
        :param count: Number of OSDs to add
        :type count: int
        :param transaction_arakoon_url: URL of the transaction arakoon
        :type transaction_arakoon_url: str
        :param buckets: Buckets to use
        :type buckets: List[str]
        :return: None
        :rtype: NoneType
        """
        self.count = count
        self.transaction_arakoon_url = transaction_arakoon_url
        self.buckets = buckets


class S3ManagerClient(AlbaBaseClient):
    """
    S3 Manager Client
    The S3 manager client mocks the 'slot' associated with an OSD as the S3 OSD does not have a slot associated with it
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
        The client has to compensate here.
        S3 has no 'slot' concept yet this plugin does.
        Solution is to mock one using the osd_id
        """
        data = self.extract_data(self._call(requests.get, 'osds', timeout=5, clean=True))  # type: list
        stack = {}
        for osd_data in data:
            osd_id = osd_data['osd_id']
            osd_data['type'] = 'S3'
            stack[osd_id] = {'osds': [dict((osd_id, osd_data))]}
        return stack

    def fill_slot(self, slot_id, extra, *args, **kwargs):
        # type: (str, dict, *any, **any) -> None
        """
        Fill a slot with a set of osds
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :param extra: Extra parameters to account for
        :type extra: OSDParams
        :return: None
        :rtype: NoneType
        """
        _ = slot_id
        osd_params = OSDParams(**extra)  # Force right arguments
        # Call can raise a NotFoundException when the slot could no longer be found
        for _ in xrange(osd_params.count):
            self._call(requests.post, 'osds', data={'transaction_arakoon_url': osd_params.transaction_arakoon_url, 'buckets': osd_params.buckets})

    def restart_osd(self, slot_id, osd_id, *args, **kwargs):
        # type: (str, str, *any, **any) -> None
        """
        Restarts a given OSD in a given Slot
        The client has to compensate here.
        S3 has no 'slot' concept yet this plugin does.
        """
        _ = slot_id
        return self._call(requests.post, 'osds/{0}/restart'.format(osd_id))

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
        raise NotImplemented('Updating the S3 OSD has not yet been implemented')

    def delete_osd(self, slot_id, osd_id, *args, **kwargs):
        # type: (str, str, *any, **any) -> None
        """
        Delete the OSD from the Slot
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :param osd_id: Identifier of the OSD
        :type osd_id: str
        :return: None
        :rtype: NoneType
        """
        _ = slot_id
        return self._call(requests.delete, 'osds/{0}'.format(osd_id))

    def build_slot_params(self, osd, *args, **kwargs):
        # type: (ovs.dal.hybrids.albaosd.AlbaOSD, *any, **any) -> dict
        """
        Builds the "extra" params for replacing an OSD
        :param osd: The OSD to generate the params for
        :type osd: ovs.dal.hybrids.albaosd.AlbaOSD
        :return: The extra param used in the create osd code
        :rtype: dict
        """
        raise NotImplemented()

    def clear_slot(self, slot_id, *args, **kwargs):
        # type: (str, *any, **any) -> None
        """
        Restart a slot
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :return: None
        :rtype: NoneType
        """
        # Slot id is the same as the osd id for the S3 OSD and only one OSD is on a mocked slot
        osd_id = slot_id
        return self._call(requests.delete, 'osds/{0}'.format(osd_id))

    def restart_slot(self, slot_id, *args, **kwargs):
        # type: (str, *any, **any) -> None
        """
        Restart a slot
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :return: None
        :rtype: NoneType
        """
        # Slot id is the same as the osd id for the S3 OSD
        osd_id = slot_id
        return self._call(requests.post, 'osds/{0}/restart'.format(osd_id))

    def stop_slot(self, slot_id, *args, **kwargs):
        # type: (str, *any, **any) -> None
        """
        Stop a slot. This will cause all OSDs on that slot to stop
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :return: None
        :rtype: NoneType
        """
        # Slot id is the same as the osd id for the S3 OSD
        osd_id = slot_id
        return self._call(requests.post, 'osds/{0}/stop'.format(osd_id))

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

    def get_service_status(self, name):
        """
        Retrieve the status of the service specified
        :param name: Name of the service to check
        :type name: str
        :return: Status of the service
        :rtype: str
        """
        return self._call(requests.get, 'service_status/{0}'.format(name))['status'][1]

    def sync_stack(self, stack, *args, **kwargs):
        # type: (dict, *any, **any) -> None
        """
        Synchronize the stack of an AlbaNode with the stack of another AlbaNode
        :param stack: Stack to sync
        :type stack: dict
        :return: None
        :rtype: Nonetype
        """
        raise NotImplementedError()
