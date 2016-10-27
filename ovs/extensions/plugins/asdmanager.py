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
import os
import time
import base64
import inspect
import logging
import requests
from ovs.log.log_handler import LogHandler
try:
    from requests.packages.urllib3 import disable_warnings
except ImportError:
    try:
        reload(requests)  # Required for 2.6 > 2.7 upgrade (new requests.packages module)
    except ImportError:
        pass  # So, this reload fails because of some FileNodeWarning that can't be found. But it did reload. Yay.
    from requests.packages.urllib3 import disable_warnings
from requests.packages.urllib3.exceptions import InsecurePlatformWarning
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from requests.packages.urllib3.exceptions import SNIMissingWarning
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)


class InvalidCredentialsError(RuntimeError):
    """
    Invalid credentials error
    """
    pass


class ASDManagerClient(object):
    """
    ASD Manager Client
    """

    disable_warnings(InsecurePlatformWarning)
    disable_warnings(InsecureRequestWarning)
    disable_warnings(SNIMissingWarning)

    test_results = {}
    test_exceptions = {}

    def __init__(self, node):
        self._logger = LogHandler.get('extensions', name='asdmanagerclient')
        self.node = node
        self.timeout = 20
        self._unittest_mode = os.environ.get('RUNNING_UNITTESTS') == 'True'
        self._log_min_duration = 1

    def _call(self, method, url, data=None, timeout=None, clean=False):
        if self._unittest_mode is True:
            curframe = inspect.currentframe()
            calframe = inspect.getouterframes(curframe, 2)
            exception = ASDManagerClient.test_exceptions.get(self.node, {}).get(calframe[1][3])
            if exception is not None:
                raise exception
            return ASDManagerClient.test_results[self.node][calframe[1][3]]

        if timeout is None:
            timeout = self.timeout
        self._refresh()
        start = time.time()
        kwargs = {'url': '{0}/{1}'.format(self._base_url, url),
                  'headers': self._base_headers,
                  'verify': False,
                  'timeout': timeout}
        if data is not None:
            kwargs['data'] = data
        response = method(**kwargs)
        try:
            data = response.json()
        except:
            raise RuntimeError(response.content)
        internal_duration = data['_duration']
        if data.get('_success', True) is False:
            error_message = data.get('_error', 'Unknown exception: {0}'.format(data))
            if error_message == 'Invalid credentials':
                raise InvalidCredentialsError(error_message)
            raise RuntimeError(error_message)
        if clean is True:
            def _clean(_dict):
                for _key in _dict.keys():
                    if _key.startswith('_'):
                        del _dict[_key]
                    elif isinstance(_dict[_key], dict):
                        _clean(_dict[_key])
            _clean(data)
        duration = time.time() - start
        if duration > self._log_min_duration:
            self._logger.info('Request "{0}" took {1:.2f} seconds (internal duration {2:.2f} seconds)'.format(inspect.stack()[1][3], duration, internal_duration))
        return data

    def get_metadata(self):
        """
        Gets metadata from the node
        """
        return self._call(requests.get, '')

    def get_disks(self):
        """
        Gets the node's disk states
        """
        return self._call(requests.get, 'disks', clean=True)

    def get_disk(self, disk_id):
        """
        Gets one of the node's disk's state
        :param disk_id: Identifier of the disk
        :type disk_id: str
        """
        return self._call(requests.get, 'disks/{0}'.format(disk_id), clean=True)

    def add_disk(self, disk_id):
        """
        Adds a disk
        :param disk_id: Identifier of the disk
        :type disk_id: str
        """
        return self._call(requests.post, 'disks/{0}/add'.format(disk_id), timeout=300)

    def remove_disk(self, disk_id):
        """
        Removes a disk
        :param disk_id: Identifier of the disk
        :type disk_id: str
        """
        return self._call(requests.post, 'disks/{0}/delete'.format(disk_id), timeout=60)

    def restart_disk(self, disk_id):
        """
        Restarts a disk
        :param disk_id: Identifier of the disk
        :type disk_id: str
        """
        return self._call(requests.post, 'disks/{0}/restart'.format(disk_id), timeout=60)

    def get_asds(self):
        """
        Loads all asds (grouped by disk)
        """
        return self._call(requests.get, 'asds', clean=True)

    def get_asds_for_disk(self, disk_id):
        """
        Loads all asds from a given disk
        :param disk_id: The disk identifier for which to load the asds
        :type disk_id: str
        """
        return self._call(requests.get, 'disks/{0}/asds'.format(disk_id), clean=True)

    def add_asd(self, disk_id):
        """
        Adds an ASD to a disk
        :param disk_id: Identifier of the disk
        :type disk_id: str
        """
        return self._call(requests.post, 'disks/{0}/asds'.format(disk_id), timeout=30)

    def restart_asd(self, disk_id, asd_id):
        """
        Restarts an ASD
        :param disk_id: Disk identifier
        :type disk_id: str
        :param asd_id: AsdID from the ASD to be restarted
        :type asd_id: str
        """
        return self._call(requests.post, 'disks/{0}/asds/{1}/restart'.format(disk_id, asd_id), timeout=30)

    def delete_asd(self, disk_id, asd_id):
        """
        Deletes an ASD from a Disk
        :param disk_id: Disk identifier
        :type disk_id: str
        :param asd_id: AsdID from the ASD to be removed
        :type asd_id: str
        """
        return self._call(requests.post, 'disks/{0}/asds/{1}/delete'.format(disk_id, asd_id), timeout=60)

    def get_update_information(self):
        """
        Checks whether update for openvstorage-sdm package is available
        :return: Latest available version and services which require a restart
        """
        return self._call(requests.get, 'update/information', timeout=120, clean=True)

    def execute_update(self, status):
        """
        Execute an update
        :param status: Status of update
        :return: None
        """
        return self._call(requests.post, 'update/execute/{0}'.format(status))

    def restart_services(self):
        """
        Restart the alba-asd-<ID> services
        :return: None
        """
        return self._call(requests.post, 'update/restart_services')

    def add_maintenance_service(self, name, alba_backend_guid, abm_name):
        """
        Add service to asd manager
        :param name: Name of the service
        :param alba_backend_guid: The guid of the AlbaBackend
        :param abm_name: The name of the ABM
        :return: result
        """
        return self._call(requests.post, 'maintenance/{0}/add'.format(name),
                          data={'alba_backend_guid': alba_backend_guid,
                                'abm_name': abm_name})

    def remove_maintenance_service(self, name):
        """
        Remove service from asd manager
        :param name: name
        :return: result
        """
        return self._call(requests.post, 'maintenance/{0}/remove'.format(name))

    def list_maintenance_services(self):
        """
        Retrieve configured maintenance services from asd manager
        :return: dict of services
        """
        return self._call(requests.get, 'maintenance')['services']

    def _refresh(self):
        self._base_url = 'https://{0}:{1}'.format(self.node.ip, self.node.port)
        self._base_headers = {'Authorization': 'Basic {0}'.format(base64.b64encode('{0}:{1}'.format(self.node.username, self.node.password)).strip())}
