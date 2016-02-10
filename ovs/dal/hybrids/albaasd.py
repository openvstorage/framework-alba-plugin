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
AlbaBackend module
"""
import time
from ovs.dal.dataobject import DataObject
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.structures import Property, Relation, Dynamic
from ovs.extensions.plugins.albacli import AlbaCLI
from ovs.extensions.storage.volatilefactory import VolatileFactory


class AlbaASD(DataObject):
    """
    The AlbaASD represents a claimed ASD
    """
    __properties = [Property('asd_id', str, doc='ASD identifier')]
    __relations = [Relation('alba_backend', AlbaBackend, 'asds', doc='The AlbaBackend that claimed the ASD'),
                   Relation('alba_node', AlbaNode, 'asds', doc='The AlbaNode to which the ASD belongs')]
    __dynamics = [Dynamic('name', str, 3600),
                  Dynamic('ip', str, 300),
                  Dynamic('port', int, 300),
                  Dynamic('info', dict, 5),
                  Dynamic('statistics', dict, 5, locked=True)]

    def _name(self):
        """
        Returns the name based on the asd_id
        """
        return self.info['name'] if self.info is not None else None

    def _ip(self):
        """
        ASD ip address
        """
        if self.info is not None:
            ips = self.info.get('ips')
            if ips:
                return ips[0]
        return self.alba_node.ip

    def _port(self):
        """
        ASD port number
        """
        return self.info['port'] if self.info is not None else None

    def _info(self):
        """
        Returns the ASD information from its node
        """
        for disk in self.alba_node.all_disks:
            if 'asd_id' in disk and disk['asd_id'] == self.asd_id:
                return disk

    def _statistics(self, dynamic):
        """
        Loads statistics from the ASD
        """
        data_keys = {'apply': ['Apply', 'Apply2'],
                     'multi_get': ['MultiGet', 'MultiGet2'],
                     'range': ['Range'],
                     'range_entries': ['RangeEntries'],
                     'statistics': ['Statistics']}
        statistics = {}
        volatile = VolatileFactory.get_client()
        prev_key = '{0}_{1}'.format(self._key, 'statistics_previous')
        previous_stats = volatile.get(prev_key, default={})
        try:
            data = AlbaCLI.run('asd-statistics', extra_params=['-h', self.ip, '-p', self.port], as_json=True)
            statistics = {'timestamp': time.time()}
            delta = statistics['timestamp'] - previous_stats.get('timestamp', statistics['timestamp'])
            for key, sources in data_keys.iteritems():
                if key not in statistics:
                    statistics[key] = {'n': 0, 'max': [], 'min': [], 'avg': []}
                for source in sources:
                    if source in data:
                        statistics[key]['n'] += data[source]['n']
                        statistics[key]['max'].append(data[source]['max'])
                        statistics[key]['min'].append(data[source]['min'])
                        statistics[key]['avg'].append(data[source]['avg'] * data[source]['n'])
                statistics[key]['max'] = max(statistics[key]['max']) if len(statistics[key]['max']) > 0 else 0
                statistics[key]['min'] = min(statistics[key]['min']) if len(statistics[key]['min']) > 0 else 0
                if statistics[key]['n'] > 0:
                    statistics[key]['avg'] = sum(statistics[key]['avg']) / float(statistics[key]['n'])
                else:
                    statistics[key]['avg'] = 0
                if key in previous_stats:
                    if delta < 0:
                        statistics[key]['n_ps'] = 0
                    elif delta == 0:
                        statistics[key]['n_ps'] = previous_stats[key].get('n_ps', 0)
                    else:
                        statistics[key]['n_ps'] = max(0, (statistics[key]['n'] - previous_stats[key]['n']) / delta)
                else:
                    statistics[key]['n_ps'] = 0
            volatile.set(prev_key, statistics, dynamic.timeout * 10)
        except Exception as ex:
            # This might fail every now and then, e.g. on disk removal. Let's ignore for now.
            pass
        return statistics
