# Copyright 2015 CloudFounders NV
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
import json
import base64
import requests


class ASDManagerClient(object):

    def __init__(self, node):
        self.node = node
        self._base_url = 'https://{0}:{1}'.format(self.node.ip, self.node.port)
        self._base_headers = {'Authorization': 'Basic {0}'.format(base64.b64encode('{0}:{1}'.format(self.node.username, self.node.password)).strip())}

    def get_metadata(self):
        """
        Gets metadata from the node
        """
        return requests.get('{0}/'.format(self._base_url),
                            headers=self._base_headers,
                            verify=False).json()

    def get_ips(self):
        """
        Gets the ips from a node
        """
        return requests.get('{0}/net'.format(self._base_url),
                            verify=False).json()['ips']

    def set_ips(self, ips):
        """
        Set primary storage ips
        """
        requests.post('{0}/net'.format(self._base_url),
                      data={'ips': json.dumps(ips)},
                      headers=self._base_headers,
                      verify=False)

    def get_disks(self, as_list=True):
        """
        Gets the node's disk states
        """
        disks = [] if as_list is True else {}
        data = requests.get('{0}/disks'.format(self._base_url),
                            headers=self._base_headers,
                            verify=False).json()
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
        """
        data = requests.get('{0}/disks/{1}'.format(self._base_url, disk),
                            headers=self._base_headers,
                            verify=False).json()
        for key in data.keys():
            if key.startswith('_'):
                del data[key]
        return data

    def add_disk(self, disk):
        """
        Adds a disk
        """
        return requests.post('{0}/disks/{1}/add'.format(self._base_url, disk),
                             headers=self._base_headers,
                             verify=False).json()

    def remove_disk(self, disk):
        """
        Removes a disk
        """
        return requests.post('{0}/disks/{1}/delete'.format(self._base_url, disk),
                             headers=self._base_headers,
                             verify=False).json()

    def restart_disk(self, disk):
        """
        Restarts a disk
        """
        return requests.post('{0}/disks/{1}/restart'.format(self._base_url, disk),
                             headers=self._base_headers,
                             verify=False).json()
