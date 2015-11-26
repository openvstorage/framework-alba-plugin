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
AlbaNode module
"""
import requests
from ovs.dal.dataobject import DataObject
from ovs.dal.structures import Property, Relation, Dynamic
from ovs.dal.hybrids.storagerouter import StorageRouter
from ovs.extensions.plugins.asdmanager import ASDManagerClient
from ovs.extensions.plugins.albacli import AlbaCLI


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
        try:
            disks = self.client.get_disks(reraise=True)
        except requests.ConnectionError:
            from ovs.dal.lists.albabackendlist import AlbaBackendList
            disks = []
            for backend in AlbaBackendList.get_albabackends():
                # All backends of this node
                config_file = '/opt/OpenvStorage/config/arakoon/{0}-abm/{0}-abm.cfg'.format(backend.name)
                osds = AlbaCLI.run('list-osds', config=config_file, as_json=True)
                for osd in osds:
                    if osd.get('node_id') == self.node_id:
                        asd_id = osd.get('long_id')
                        if osd.get('decommissioned') is True:
                            state = {'state': 'decommissioned'}
                        else:
                            state = {'state': 'error', 'detail': 'nodedown'}
                        disks.append({'asd_id': asd_id,
                                      'node_id': osd.get('node_id'),
                                      'port': osd.get('port'),
                                      'available': False,
                                      'state': state,
                                      'log_level': 'info',
                                      'device': asd_id,
                                      'home': asd_id,
                                      'mountpoint': asd_id,
                                      'name': asd_id,
                                      'usage': {'available': 0, 'size': 0, 'used': 0},
                                      })
        return disks
