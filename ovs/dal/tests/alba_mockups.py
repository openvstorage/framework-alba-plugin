#  Copyright 2015 iNuron NV
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
Mockups module
"""


class AlbaCLI(object):
    """
    Mocks the AlbaCLI
    """

    run_results = {}

    def __init__(self):
        """
        Dummy init method
        """
        pass

    @staticmethod
    def run(command, *args, **kwargs):
        """
        Return fake info
        """
        _ = args, kwargs
        return AlbaCLI.run_results[command]


class AlbaCLIModule:
    """
    Mocks the AlbaCLI module
    """

    AlbaCLI = AlbaCLI


class ASDManagerClient(object):
    """ ASD Manager Client """

    results = {}

    def __init__(self, node):
        """
        Dummy init method
        """
        _ = node
        pass

    def get_metadata(self):
        """
        Gets metadata from the node
        """
        _ = self
        return ASDManagerClient.results.get('get_metadata')

    def get_disks(self, as_list=True, reraise=False):
        """
        Gets the node's disk states
        :param as_list: Return a list if True else dictionary
        :param reraise: Raise exception if True and error occurs
        """
        _ = self, as_list, reraise
        return ASDManagerClient.results.get('get_disks')

    def get_disk(self, disk):
        """
        Gets one of the node's disk's state
        :param disk: Guid of the disk
        """
        _ = self, disk
        return ASDManagerClient.results.get('get_disk')

    def add_disk(self, disk):
        """
        Adds a disk
        :param disk: Guid of the disk
        """
        _ = self, disk
        return ASDManagerClient.results.get('add_disk')

    def remove_disk(self, disk):
        """
        Removes a disk
        :param disk: Guid of the disk
        """
        _ = self, disk
        return ASDManagerClient.results.get('remove_disk')

    def restart_disk(self, disk):
        """
        Restarts a disk
        :param disk: Guid of the disk
        """
        _ = self, disk
        return ASDManagerClient.results.get('restart_disk')

    def get_update_information(self):
        """
        Checks whether update for openvstorage-sdm package is available
        :return: Latest available version and services which require a restart
        """
        _ = self
        return ASDManagerClient.results.get('get_update_information')

    def execute_update(self, status):
        """
        Execute an update
        :param status: Status of update
        :return: None
        """
        _ = self, status
        return ASDManagerClient.results.get('execute_update')

    def restart_services(self):
        """
        Restart the alba-asd-<ID> services
        :return: None
        """
        _ = self
        return ASDManagerClient.results.get('restart_services')


class ASDManagerModule:
    """
    Mocks the ASDManagerClient module
    """

    ASDManagerClient = ASDManagerClient
