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
NSMService module
"""
from ovs.dal.dataobject import DataObject
from ovs.dal.structures import Relation
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.service import Service


class ABMService(DataObject):
    """
    The ABMService class represents the junction table between the (albamanager)Service and AlbaBackend.
    Examples:
    * my_alba_backend.abm_services[0].service
    * my_service.abm_service.alba_backend
    """
    __properties = []
    __relations = [Relation('alba_backend', AlbaBackend, 'abm_services'),
                   Relation('service', Service, 'abm_service', onetoone=True)]
    __dynamics = []
