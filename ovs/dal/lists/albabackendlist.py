# Copyright 2014 iNuron NV
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
AlbaBackendList module
"""
from ovs.dal.datalist import DataList
from ovs.dal.dataobject import DataObjectList
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.helpers import Descriptor


class AlbaBackendList(object):
    """
    This AlbaBackendList class contains various lists regarding to the AlbaBackend class
    """

    @staticmethod
    def get_albabackends():
        """
        Returns a list of all ALBABackends
        """
        backends = DataList({'object': AlbaBackend,
                             'data': DataList.select.GUIDS,
                             'query': {'type': DataList.where_operator.AND,
                                       'items': []}}).data
        return DataObjectList(backends, AlbaBackend)

    @staticmethod
    def get_by_alba_id(alba_id):
        """
        Gets an AlbaBackend by the alba_id
        """
        backends = DataList({'object': AlbaBackend,
                          'data': DataList.select.GUIDS,
                          'query': {'type': DataList.where_operator.AND,
                                    'items': [('alba_id', DataList.operator.EQUALS, alba_id)]}}).data
        if len(backends) == 1:
            return Descriptor(AlbaBackend, backends[0]).get_object(True)
        return None
