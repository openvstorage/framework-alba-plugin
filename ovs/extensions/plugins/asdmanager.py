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
import json
import time
import base64
import inspect
import logging
import requests
from ovs_extensions.generic.exceptions import InvalidCredentialsError, NotFoundError
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
        self.node = node
        self.timeout = 20

        self._logger = LogHandler.get('extensions', name='asdmanagerclient')
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

        # Refresh URL / headers
        self._base_url = 'https://{0}:{1}'.format(self.node.ip, self.node.port)
        self._base_headers = {'Authorization': 'Basic {0}'.format(base64.b64encode('{0}:{1}'.format(self.node.username, self.node.password)).strip())}

        start = time.time()
        kwargs = {'url': '{0}/{1}'.format(self._base_url, url),
                  'headers': self._base_headers,
                  'verify': False,
                  'timeout': timeout}
        if data is not None:
            kwargs['data'] = data
        response = method(**kwargs)
        if response.status_code == 404:
            raise NotFoundError('URL not found: {0}'.format(kwargs['url']))
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

    # Slot based

    def get_stack(self):
        """
        Gets the remote node stack
        """
        # Version 3 introduced 'slots'
        if self.get_metadata()['_version'] >= 3:
            data = self._call(requests.get, 'slots', timeout=5, clean=True)
            for slot_info in data.itervalues():
                for osd in slot_info.get('osds', {}).itervalues():
                    osd['type'] = 'ASD'
            return data

        # Version 2 and older used AlbaDisk
        data = self._call(method=requests.get, url='disks', timeout=5, clean=True)
        for disk_id, value in data.iteritems():
            value[u'osds'] = self._call(method=requests.get, url='disks/{0}/asds'.format(disk_id), clean=True)
            value[u'state'] = 'empty' if len(value['osds']) == 0 else 'ok'
            for osd_id, osd_info in value['osds'].iteritems():
                osd_info[u'type'] = 'ASD'
                osd_info[u'hosts'] = osd_info['ips']
                osd_info[u'folder'] = osd_id
        return data

    def fill_slot(self, slot_id, extra):
        """
        Fills a slot (disk) with one or more OSDs
        """
        for _ in xrange(extra['count']):
            self._call(requests.post, 'slots/{0}/asds'.format(slot_id))

    def restart_osd(self, slot_id, osd_id):
        """
        Restarts a given OSD in a given Slot
        """
        return self._call(requests.post, 'slots/{0}/asds/{1}/restart'.format(slot_id, osd_id))

    def update_osd(self, slot_id, osd_id, update_data):
        """
        Updates a given OSD in a given Slot
        """
        return self._call(method=requests.post,
                          url='slots/{0}/asds/{1}/update'.format(slot_id, osd_id),
                          data={'update_data': json.dumps(update_data)})

    def delete_osd(self, slot_id, osd_id):
        """
        Deletes the OSD from the Slot
        """
        return self._call(requests.delete, 'slots/{0}/asds/{1}'.format(slot_id, osd_id))

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
        return self._call(requests.post, 'slots/{0}/restart'.format(slot_id))

    def get_metadata(self):
        """
        Gets metadata from the node
        """
        return self._call(requests.get, '')

    def get_package_information(self):
        """
        Retrieve the package information for this ALBA node
        :return: Latest available version and services which require a restart
        """
        # For backwards compatibility we first attempt to retrieve using the newest API
        try:
            return self._call(requests.get, 'update/package_information', timeout=120, clean=True)
        except NotFoundError:
            update_info = self._call(requests.get, 'update/information', timeout=120, clean=True)
            if update_info['version']:
                return {'alba': {'openvstorage-sdm': {'candidate': update_info['version'],
                                                      'installed': update_info['installed'],
                                                      'services_to_restart': []}}}
            return {}

    def execute_update(self, package_name):
        """
        Execute an update
        :return: None
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
