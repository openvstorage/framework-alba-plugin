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
from ovs.dal.dataobject import DataObject
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.structures import Property, Relation, Dynamic
from ovs.extensions.plugins.albacli import AlbaCLI


class AlbaASD(DataObject):
    """
    The AlbaASD represents a claimed ASD
    """
    __properties = [Property('asd_id', str, doc='ASD identifier')]
    __relations = [Relation('alba_backend', AlbaBackend, 'asds', doc='The AlbaBackend that claimed the ASD'),
                   Relation('alba_node', AlbaNode, 'asds', doc='The AlbaNode to which the ASD belongs')]
    __dynamics = [Dynamic('name', str, 3600),
                  Dynamic('info', dict, 5),
                  Dynamic('statistics', dict, 5, locked=True)]

    def _name(self):
        """
        Returns the name based on the asd_id
        """
        return self.info['name'] if self.info is not None else None

    def _info(self):
        """
        Returns the ASD information from its node
        """
        for disk in self.alba_node.all_disks:
            if disk['asd_id'] == self.asd_id:
                return disk

    def _statistics(self):
        """
        Loads statistics from the ASD
        """
        data_keys = {'apply': ['Apply', 'Apply2'],
                     'multi_get': ['MultiGet', 'MultiGet2'],
                     'range': ['Range'],
                     'range_entries': ['RangeEntries'],
                     'statistics': ['Statistics']}
        config_file = '/opt/OpenvStorage/config/arakoon/{0}-abm/{0}-abm.cfg'.format(self.alba_backend.backend.name)
        try:
            data = AlbaCLI.run('asd-statistics', long_id=self.asd_id, config=config_file, extra_params='--clear', as_json=True)
            statistics = {'creation': data['creation'],
                          'period': data['period']}
            for key, sources in data_keys.iteritems():
                if key not in statistics:
                    statistics[key] = {'n': 0, 'max': [], 'min': [], 'avg': []}
                for source in sources:
                    if source in data:
                        statistics[key]['n'] += data[source]['n']
                        statistics[key]['max'].append(data[source]['max'])
                        statistics[key]['min'].append(data[source]['min'])
                        statistics[key]['avg'].append(data[source]['avg'] * data[source]['n'])
                if data['period'] > 0:
                    statistics[key]['n_ps'] = statistics[key]['n'] / float(data['period'])
                else:
                    statistics[key]['n_ps'] = 0
                statistics[key]['max'] = max(statistics[key]['max']) if len(statistics[key]['max']) > 0 else 0
                statistics[key]['min'] = min(statistics[key]['min']) if len(statistics[key]['min']) > 0 else 0
                if statistics[key]['n'] > 0:
                    statistics[key]['avg'] = sum(statistics[key]['avg']) / float(statistics[key]['n'])
                else:
                    statistics[key]['avg'] = 0
            return statistics
        except:
            # This might fail every now and then, e.g. on disk removal. Let's ignore for now.
            return None
