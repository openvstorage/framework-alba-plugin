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
from ovs.dal.lists.vpoollist import VPoolList
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.hybrids.backend import Backend
from ovs.dal.structures import Property, Relation, Dynamic
from ovs.extensions.plugins.albacli import AlbaCLI


class AlbaBackend(DataObject):
    """
    The AlbaBackend provides ALBA specific information
    """
    __properties = [Property('alba_id', str, mandatory=False, doc='ALBA internal identifier')]
    __relations = [Relation('backend', Backend, 'alba_backend', onetoone=True, doc='Linked generic backend')]
    __dynamics = [Dynamic('all_disks', list, 5),
                  Dynamic('statistics', dict, 5),
                  Dynamic('ns_statistics', dict, 60),
                  Dynamic('presets', list, 60),
                  Dynamic('available', bool, 60),
                  Dynamic('name', str, 3600)]

    def _all_disks(self):
        """
        Returns a live list of all disks known to this AlbaBackend
        """
        from ovs.dal.lists.albanodelist import AlbaNodeList
        from ovs.dal.lists.albabackendlist import AlbaBackendList
        config_file = '/opt/OpenvStorage/config/arakoon/{0}-abm/{0}-abm.cfg'.format(self.backend.name)
        all_osds = AlbaCLI.run('list-all-osds', config=config_file, as_json=True)
        disks = []
        for node in AlbaNodeList.get_albanodes():
            asds = node.asds
            for disk in node.all_disks:
                if disk['available'] is True:
                    disk['status'] = 'uninitialized'
                else:
                    if disk['state']['state'] == 'ok':
                        disk['status'] = 'initialized'
                        for osd in all_osds:
                            if osd['node_id'] == node.node_id and 'asd_id' in disk and osd['long_id'] == disk['asd_id']:
                                if osd['id'] is None:
                                    if osd['alba_id'] is None:
                                        disk['status'] = 'available'
                                    else:
                                        disk['status'] = 'unavailable'
                                        other_abackend = AlbaBackendList.get_by_alba_id(osd['alba_id'])
                                        if other_abackend is not None:
                                            disk['alba_backend_guid'] = other_abackend.guid
                                else:
                                    disk['status'] = 'claimed'
                                    disk['alba_backend_guid'] = self.guid
                                    for asd in asds:
                                        if asd.asd_id == disk['asd_id']:
                                            stats = asd.statistics
                                            if stats['apply']['max'] > 1 or stats['multi_get']['max'] > 1:
                                                disk['status'] = 'error'
                                                disk['status_detail'] = 'tooslow'
                                            elif stats['apply']['max'] > 0.5 or stats['multi_get']['max'] > 0.5:
                                                disk['status'] = 'warning'
                                                disk['status_detail'] = 'slow'
                                    if disk['status'] == 'claimed':
                                        if len(osd['errors']) > 0 and (len(osd['read'] + osd['write']) == 0 or min(osd['read'] + osd['write']) < max(float(error[0]) for error in osd['errors']) + 3600):
                                            disk['status'] = 'warning'
                                            disk['status_detail'] = 'recenterrors'
                    elif disk['state']['state'] == 'decommissioned':
                        disk['status'] = 'unavailable'
                        disk['status_detail'] = 'decommissioned'
                    else:
                        disk['status'] = 'error'
                        disk['status_detail'] = disk['state']['detail']
                        for osd in all_osds:
                            if osd['node_id'] == node.node_id and 'asd_id' in disk and osd['long_id'] == disk['asd_id']:
                                other_abackend = AlbaBackendList.get_by_alba_id(osd['alba_id'])
                                if other_abackend is not None:
                                    disk['alba_backend_guid'] = other_abackend.guid
                disks.append(disk)
        return disks

    def _statistics(self):
        """
        Returns statistics for all its asds
        """
        data_keys = ['apply', 'multi_get', 'range', 'range_entries', 'statistics']
        statistics = {}
        for key in data_keys:
            statistics[key] = {'n': 0,
                               'n_ps': 0,
                               'avg': [],
                               'max': [],
                               'min': []}
        for asd in self.asds:
            asd_stats = asd.statistics
            if asd_stats is None:
                continue
            for key in data_keys:
                statistics[key]['n'] += asd_stats[key]['n']
                statistics[key]['n_ps'] += asd_stats[key]['n_ps']
                statistics[key]['avg'].append(asd_stats[key]['avg'])
                statistics[key]['max'].append(asd_stats[key]['max'])
                statistics[key]['min'].append(asd_stats[key]['min'])
        for key in data_keys:
            statistics[key]['max'] = max(statistics[key]['max']) if len(statistics[key]['max']) > 0 else 0
            statistics[key]['min'] = min(statistics[key]['min']) if len(statistics[key]['min']) > 0 else 0
            if len(statistics[key]['avg']) > 0:
                statistics[key]['avg'] = sum(statistics[key]['avg']) / len(statistics[key]['avg'])
            else:
                statistics[key]['avg'] = 0
        statistics['creation'] = time.time()
        return statistics

    def _ns_statistics(self):
        """
        Returns a list of the ASDs namespaces
        """
        # Collect ALBA related statistics
        alba_dataset = {}
        config_file = '/opt/OpenvStorage/config/arakoon/{0}-abm/{0}-abm.cfg'.format(self.backend.name)
        namespaces = AlbaCLI.run('list-namespaces', config=config_file, as_json=True)
        for namespace_data in namespaces:
            if namespace_data['state'] != 'active':
                continue
            namespace = namespace_data['name']
            try:
                alba_dataset[namespace] = AlbaCLI.run('show-namespace', config=config_file, as_json=True, extra_params=namespace)
            except:
                # This might fail every now and then, e.g. on disk removal. Let's ignore for now.
                pass
        # Collect vPool/vDisk data
        vdisk_dataset = {}
        for vpool in VPoolList.get_vpools():
            if vpool not in vdisk_dataset:
                vdisk_dataset[vpool] = []
            for vdisk in vpool.vdisks:
                vdisk_dataset[vpool].append(vdisk.volume_id)
        # Load disk statistics
        global_usage = {'size': 0,
                        'used': 0}
        nodes = set()
        asds = []
        for asd in self.asds:
            asds.append(asd.asd_id)
            if asd.alba_node not in nodes:
                nodes.add(asd.alba_node)
        for node in nodes:
            for asd in node.all_disks:
                if 'asd_id' in asd and asd['asd_id'] in asds and 'usage' in asd:
                    global_usage['size'] += asd['usage']['size']
                    global_usage['used'] += asd['usage']['used']
        # Cross merge
        dataset = {'global': {'size': global_usage['size'],
                              'used': global_usage['used']},
                   'vpools': {},
                   'unknown': {'storage': 0,
                               'logical': 0}}
        for vpool in vdisk_dataset:
            for namespace in vdisk_dataset[vpool]:
                if namespace in alba_dataset:
                    if vpool.guid not in dataset['vpools']:
                        dataset['vpools'][vpool.guid] = {'storage': 0,
                                                         'logical': 0}
                    dataset['vpools'][vpool.guid]['storage'] += alba_dataset[namespace]['storage']
                    dataset['vpools'][vpool.guid]['logical'] += alba_dataset[namespace]['logical']
                    del alba_dataset[namespace]
            fd_namespace = 'fd-{0}-{1}'.format(vpool.name, vpool.guid)
            if fd_namespace in alba_dataset:
                if vpool.guid not in dataset['vpools']:
                    dataset['vpools'][vpool.guid] = {'storage': 0,
                                                     'logical': 0}
                dataset['vpools'][vpool.guid]['storage'] += alba_dataset[fd_namespace]['storage']
                dataset['vpools'][vpool.guid]['logical'] += alba_dataset[fd_namespace]['logical']
                del alba_dataset[fd_namespace]
        for namespace in alba_dataset:
            dataset['unknown']['storage'] += alba_dataset[namespace]['storage']
            dataset['unknown']['logical'] += alba_dataset[namespace]['logical']
        return dataset

    def _presets(self):
        """
        Returns the policies active on the node
        """
        all_disks = self.all_disks
        disks = {}
        for node in AlbaNodeList.get_albanodes():
            disks[node.node_id] = 0
            for disk in all_disks:
                if disk['node_id'] == node.node_id and disk['status'] in ['claimed', 'warning']:
                    disks[node.node_id] += 1
        config_file = '/opt/OpenvStorage/config/arakoon/{0}-abm/{0}-abm.cfg'.format(self.backend.name)
        presets = AlbaCLI.run('list-presets', config=config_file, as_json=True)
        preset_dict = {}
        for preset in presets:
            preset_dict[preset['name']] = preset
            if 'in_use' not in preset:
                preset['in_use'] = True
            if 'is_default' not in preset:
                preset['is_default'] = False
            preset['is_available'] = False
            preset['policies'] = [tuple(policy) for policy in preset['policies']]
            preset['policy_metadata'] = {}
            active_policy = None
            for policy in preset['policies']:
                is_available = False
                available_disks = sum(min(disks[node], policy[3]) for node in disks)
                if available_disks >= policy[2]:
                    if active_policy is None:
                        active_policy = policy
                    is_available = True
                preset['policy_metadata'][policy] = {'is_active': False, 'in_use': False, 'is_available': is_available}
                preset['is_available'] |= is_available
            if active_policy is not None:
                preset['policy_metadata'][active_policy]['is_active'] = True
        namespaces = AlbaCLI.run('list-namespaces', config=config_file, as_json=True)
        for namespace_data in namespaces:
            if namespace_data['state'] == 'active':
                namespace = namespace_data['name']
                try:
                    policy_usage = AlbaCLI.run('show-namespace', config=config_file, as_json=True,
                                               extra_params=namespace)['bucket_count']
                except:
                    continue
                preset = preset_dict[namespace_data['preset_name']]
                for usage in policy_usage:
                    upolicy = tuple(usage[0])  # Policy as reported to be "in use"
                    for cpolicy in preset['policies']:  # All configured policies
                        if upolicy[0] == cpolicy[0] and upolicy[1] == cpolicy[1] and upolicy[3] <= cpolicy[3]:
                            preset['policy_metadata'][cpolicy]['in_use'] = True
                            break
        for preset in presets:
            preset['policies'] = [str(policy) for policy in preset['policies']]
            for key in preset['policy_metadata'].keys():
                preset['policy_metadata'][str(key)] = preset['policy_metadata'][key]
                del preset['policy_metadata'][key]
        return presets

    def _available(self):
        """
        Returns True if the backend can be used
        """
        return self.backend.status == 'RUNNING'

    def _name(self):
        """
        Returns the backend's name
        """
        return self.backend.name
