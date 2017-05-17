# Copyright (C) 2016 iNuron NV
#
# This file is part of Open vStorage Open Source Edition (OSE),
# as available from
#
#      http://www.openvstorage.org and
#      http://www.openvstorage.com.
#
# This file is free software; you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License v3 (GNU AGPLv3)
# as published by the Free Software Foundation, in version 3 as it comes
# in the LICENSE.txt file of the Open vStorage OSE distribution.
#
# Open vStorage is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY of any kind.

"""
AlbaOSD module
"""
import time
from ovs.dal.dataobject import DataObject
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.albadisk import AlbaDisk
from ovs.dal.hybrids.domain import Domain
from ovs.dal.structures import Property, Relation, Dynamic
from ovs_extensions.storage.volatilefactory import VolatileFactory


class AlbaOSD(DataObject):
    """
    The AlbaOSD represents a claimed ASD or an AlbaBackend
    """
    OSD_TYPES = DataObject.enumerator('Osd_type', ['ASD', 'ALBA_BACKEND'])

    __properties = [Property('osd_id', str, doc='OSD identifier'),
                    Property('osd_type', OSD_TYPES.keys(), doc='Type of OSD (ASD, ALBA_BACKEND)'),
                    Property('metadata', dict, mandatory=False, doc='Additional information about this OSD, such as connection information (if OSD is an ALBA backend')]
    __relations = [Relation('alba_backend', AlbaBackend, 'osds', doc='The AlbaBackend that claimed the OSD'),
                   Relation('alba_disk', AlbaDisk, 'osds', mandatory=False, doc='The AlbaDisk to which the OSD belongs'),
                   Relation('domain', Domain, 'osds', mandatory=False, doc='The Domain in which the OSD resides')]
    __dynamics = [Dynamic('statistics', dict, 5, locked=True)]

    def _statistics(self, dynamic):
        """
        Loads statistics from the ASD
        """
        data_keys = {'apply': ['Apply', 'Apply2'],
                     'multi_get': ['MultiGet', 'MultiGet2'],
                     'range': ['Range'],
                     'range_entries': ['RangeEntries'],
                     'statistics': ['Statistics']}
        volatile = VolatileFactory.get_client()
        prev_key = '{0}_{1}'.format(self._key, 'statistics_previous')
        previous_stats = volatile.get(prev_key, default={})
        try:
            all_statistics = self.alba_backend.asd_statistics
            if self.osd_id not in all_statistics:
                return {}
            data = all_statistics[self.osd_id]
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
            return statistics
        except Exception:
            # This might fail every now and then, e.g. on disk removal. Let's ignore for now.
            return {}
