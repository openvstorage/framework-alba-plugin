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
AlbaDisk module
"""
from ovs.dal.dataobject import DataObject
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.structures import Property, Relation


class AlbaDisk(DataObject):
    """
    The AlbaDisk represents a disk hosting zero or more ASDs
    """
    __properties = [Property('name', str, doc='The disk name')]
    __relations = [Relation('alba_node', AlbaNode, 'disks', doc='The AlbaNode to which the AlbaDisk belongs')]
    __dynamics = []
