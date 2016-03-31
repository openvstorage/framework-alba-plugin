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
AlbaBackendList module
"""
from ovs.dal.datalist import DataList
from ovs.dal.hybrids.albabackend import AlbaBackend


class AlbaBackendList(object):
    """
    This AlbaBackendList class contains various lists regarding to the AlbaBackend class
    """

    @staticmethod
    def get_albabackends():
        """
        Returns a list of all ALBABackends
        """
        return DataList(AlbaBackend, {'type': DataList.where_operator.AND,
                                      'items': []})

    @staticmethod
    def get_by_alba_id(alba_id):
        """
        Gets an AlbaBackend by the alba_id
        """
        backends = DataList(AlbaBackend, {'type': DataList.where_operator.AND,
                                          'items': [('alba_id', DataList.operator.EQUALS, alba_id)]})
        if len(backends) == 1:
            return backends[0]
        return None
