# Copyright 2016 iNuron NV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Generic ALBA CLI module
"""
import base64
import inspect
import requests
import time
from ovs.log.logHandler import LogHandler


class ASDManagerClient(object):
    """ ASD Manager Client """
    def __init__(self, node):
        self._logger = LogHandler.get('extensions', name='asdmanagerclient')
        self.node = node
        self.timeout = 20
        self._log_min_duration = 1

    def get_metadata(self):
        """
        Gets metadata from the node
        """
        self._refresh()
        start = time.time()
        data = requests.get('{0}/'.format(self._base_url),
                            headers=self._base_headers,
                            verify=False,
                            timeout=self.timeout).json()
        duration = time.time() - start
        if duration > self._log_min_duration:
            self._logger.info('Request "{0}" took {1:.2f} seconds (internal duration {2:.2f} seconds)'.format(inspect.currentframe().f_code.co_name, duration, data['_duration']))
        return data

    def get_disks(self, as_list=True, reraise=False):
        """
        Gets the node's disk states
        :param as_list: Return a list if True else dictionary
        :param reraise: Raise exception if True and error occurs
        """
        self._refresh()
        disks = [] if as_list is True else {}
        start = time.time()
        try:
            data = requests.get('{0}/disks'.format(self._base_url),
                                headers=self._base_headers,
                                verify=False,
                                timeout=self.timeout).json()
            duration = time.time() - start
            if duration > self._log_min_duration:
                self._logger.info('Request "{0}" took {1:.2f} seconds (internal duration {2:.2f} seconds)'.format(inspect.currentframe().f_code.co_name, duration, data['_duration']))
        except requests.ConnectionError as ex:
            self._logger.error('Could not load data: {0}'.format(ex))
            if reraise is True:
                raise ex
            return disks
        for disk in data.keys():
            if not disk.startswith('_'):
                for key in data[disk].keys():
                    if key.startswith('_'):
                        del data[disk][key]
                if as_list is True:
                    disks.append(data[disk])
                else:
                    disks[disk] = data[disk]
        return disks

    def get_disk(self, disk):
        """
        Gets one of the node's disk's state
        :param disk: Guid of the disk
        """
        self._refresh()
        start = time.time()
        data = requests.get('{0}/disks/{1}'.format(self._base_url, disk),
                            headers=self._base_headers,
                            verify=False,
                            timeout=self.timeout).json()
        duration = time.time() - start
        if duration > self._log_min_duration:
            self._logger.info('Request "{0}" took {1:.2f} seconds (internal duration {2:.2f} seconds)'.format(inspect.currentframe().f_code.co_name, duration, data['_duration']))

        for key in data.keys():
            if key.startswith('_'):
                del data[key]
        return data

    def add_disk(self, disk):
        """
        Adds a disk
        :param disk: Guid of the disk
        """
        self._refresh()
        start = time.time()
        data = requests.post('{0}/disks/{1}/add'.format(self._base_url, disk),
                             headers=self._base_headers,
                             verify=False,
                             timeout=self.timeout).json()
        duration = time.time() - start
        if duration > self._log_min_duration:
            self._logger.info('Request "{0}" took {1:.2f} seconds (internal duration {2:.2f} seconds)'.format(inspect.currentframe().f_code.co_name, duration, data['_duration']))
        return data

    def remove_disk(self, disk):
        """
        Removes a disk
        :param disk: Guid of the disk
        """
        self._refresh()
        start = time.time()
        data = requests.post('{0}/disks/{1}/delete'.format(self._base_url, disk),
                             headers=self._base_headers,
                             verify=False,
                             timeout=self.timeout).json()
        duration = time.time() - start
        if duration > self._log_min_duration:
            self._logger.info('Request "{0}" took {1:.2f} seconds (internal duration {2:.2f} seconds)'.format(inspect.currentframe().f_code.co_name, duration, data['_duration']))
        return data

    def restart_disk(self, disk):
        """
        Restarts a disk
        :param disk: Guid of the disk
        """
        self._refresh()
        start = time.time()
        data = requests.post('{0}/disks/{1}/restart'.format(self._base_url, disk),
                             headers=self._base_headers,
                             verify=False,
                             timeout=self.timeout).json()
        duration = time.time() - start
        if duration > self._log_min_duration:
            self._logger.info('Request "{0}" took {1:.2f} seconds (internal duration {2:.2f} seconds)'.format(inspect.currentframe().f_code.co_name, duration, data['_duration']))
        return data

    def get_update_information(self):
        """
        Checks whether update for openvstorage-sdm package is available
        :return: Latest available version and services which require a restart
        """
        self._refresh()
        start = time.time()
        data = requests.get('{0}/update/information'.format(self._base_url),
                            headers=self._base_headers,
                            verify=False,
                            timeout=120).json()
        duration = time.time() - start
        if duration > self._log_min_duration:
            self._logger.info('Request "{0}" took {1:.2f} seconds (internal duration {2:.2f} seconds)'.format(inspect.currentframe().f_code.co_name, duration, data['_duration']))

        for key in data.keys():
            if key.startswith('_'):
                del data[key]
        return data

    def execute_update(self, status):
        """
        Execute an update
        :param status: Status of update
        :return: None
        """
        self._refresh()
        start = time.time()
        data = requests.post('{0}/update/execute/{1}'.format(self._base_url, status),
                             headers=self._base_headers,
                             verify=False,
                             timeout=self.timeout).json()
        duration = time.time() - start
        if duration > self._log_min_duration:
            self._logger.info('Request "{0}" took {1:.2f} seconds (internal duration {2:.2f} seconds)'.format(inspect.currentframe().f_code.co_name, duration, data['_duration']))
        return data

    def restart_services(self):
        """
        Restart the alba-asd-<ID> services
        :return: None
        """
        self._refresh()
        start = time.time()
        data = requests.post('{0}/update/restart_services'.format(self._base_url),
                             headers=self._base_headers,
                             verify=False,
                             timeout=self.timeout).json()
        duration = time.time() - start
        if duration > self._log_min_duration:
            self._logger.info('Request "{0}" took {1:.2f} seconds (internal duration {2:.2f} seconds)'.format(inspect.currentframe().f_code.co_name, duration, data['_duration']))
        return data

    def _refresh(self):
        self._base_url = 'https://{0}:{1}'.format(self.node.ip, self.node.port)
        self._base_headers = {'Authorization': 'Basic {0}'.format(base64.b64encode('{0}:{1}'.format(self.node.username, self.node.password)).strip())}

    def add_maintenance_service(self, name, alba_backend_guid, abm_name):
        """
        Add service to asd manager
        :param name: name
        :param abm_name:
        :param alba_backend_guid:
        :return: result
        """
        self._refresh()
        start = time.time()
        data = requests.post('{0}/maintenance/{1}/add'.format(self._base_url, name),
                             headers=self._base_headers,
                             data={'alba_backend_guid': alba_backend_guid,
                                   'abm_name': abm_name},
                             verify=False,
                             timeout=self.timeout).json()
        print data
        duration = time.time() - start
        if duration > self._log_min_duration:
            self._logger.info('Request "{0}" took {1:.2f} seconds (internal duration {2:.2f} seconds)'.format(inspect.currentframe().f_code.co_name, duration, data['_duration']))
        return data

    def remove_maintenance_service(self, name):
        """
        Remove service from asd manager
        :param name: name
        :return: result
        """
        self._refresh()
        start = time.time()
        data = requests.post('{0}/maintenance/{1}/remove'.format(self._base_url, name),
                             headers=self._base_headers,
                             verify=False,
                             timeout=self.timeout).json()
        duration = time.time() - start
        if duration > self._log_min_duration:
            self._logger.info('Request "{0}" took {1:.2f} seconds (internal duration {2:.2f} seconds)'.format(inspect.currentframe().f_code.co_name, duration, data['_duration']))
        return data

    def list_maintenance_services(self):
        """
        Retrieve configured maintenance services from asd manager
        :return: dict of services
        """
        self._refresh()
        start = time.time()
        data = requests.get('{0}/maintenance'.format(self._base_url),
                            headers=self._base_headers,
                            verify=False,
                            timeout=self.timeout).json()
        duration = time.time() - start
        if duration > self._log_min_duration:
            self._logger.info('Request "{0}" took {1:.2f} seconds (internal duration {2:.2f} seconds)'.format(inspect.currentframe().f_code.co_name, duration, data['_duration']))
        return data
