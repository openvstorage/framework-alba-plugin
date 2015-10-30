# Copyright 2014 iNuron NV
#
# Licensed under the Open vStorage Non-Commercial License, Version 1.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.openvstorage.org/OVS_NON_COMMERCIAL
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
AlbaNode module
"""
from ovs.dal.dataobject import DataObject
from ovs.dal.structures import Property, Relation, Dynamic
from ovs.dal.hybrids.storagerouter import StorageRouter
from ovs.extensions.plugins.asdmanager import ASDManagerClient


class AlbaNode(DataObject):
    """
    The AlbaNode contains information about nodes (containing OSDs)
    """
    __properties = [Property('ip', str, doc='IP Address'),
                    Property('port', int, doc='Port'),
                    Property('node_id', str, doc='Alba node_id identifier'),
                    Property('username', str, doc='Username of the AlbaNode'),
                    Property('password', str, doc='Password of the AlbaNode'),
                    Property('type', ['ASD', 'SUPERMICRO'], default='ASD', doc='The type of the AlbaNode')]
    __relations = [Relation('storagerouter', StorageRouter, 'alba_nodes', mandatory=False, doc='StorageRouter hosting the AlbaNode')]
    __dynamics = [Dynamic('ips', list, 3600),
                  Dynamic('all_disks', list, 5)]

    def __init__(self, *args, **kwargs):
        """
        Initializes an AlbaNode, setting up its additional helpers
        """
        DataObject.__init__(self, *args, **kwargs)
        self._frozen = False
        self.client = ASDManagerClient(self)
        self._frozen = True

    def _ips(self):
        """
        Returns the IPs of the node
        """
        return self.client.get_ips()

    def _all_disks(self):
        """
        Returns a live list of all disks on this node
        """
        return self.client.get_disks()
