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
from Queue import Queue, Empty
from threading import Thread
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
                  Dynamic('ns_data', list, 60),
                  Dynamic('ns_statistics', dict, 60),
                  Dynamic('presets', list, 60),
                  Dynamic('available', bool, 60),
                  Dynamic('name', str, 3600),
                  Dynamic('metadata_information', dict, 60)]

    def _all_disks(self):
        """
        Returns a live list of all disks known to this AlbaBackend
        """
        from ovs.dal.lists.albanodelist import AlbaNodeList
        from ovs.dal.lists.albabackendlist import AlbaBackendList

        alba_backend_map = {}
        for a_backend in AlbaBackendList.get_albabackends():
            alba_backend_map[a_backend.alba_id] = a_backend
        node_disk_map = {}
        alba_nodes = AlbaNodeList.get_albanodes()
        for node in alba_nodes:
            node_disk_map[node.node_id] = []

        # Load OSDs
        config = 'etcd://127.0.0.1:2379/ovs/arakoon/{0}-abm/config'.format(self.backend.name)
        for found_osd in AlbaCLI.run('list-all-osds', config=config, as_json=True):
            node_id = found_osd['node_id']
            if node_id in node_disk_map:
                node_disk_map[node_id].append({'osd': found_osd})

        # Load all_disk information
        def load_disks(_node, _list):
            for _disk in _node.all_disks:
                found = False
                for container in _list:
                    if container['osd']['long_id'] == _disk.get('asd_id'):
                        container['disk'] = _disk
                        found = True
                        break
                if found is False:
                    _list.append({'disk': _disk})
        threads = []
        for node in alba_nodes:
            thread = Thread(target=load_disks, args=(node, node_disk_map[node.node_id]))
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()

        # Make mapping between node IDs and the relevant OSDs and disks
        def process_disk(_info, _disks, _node):
            disk = _info.get('disk')
            if disk is None:
                return
            disk_status = 'uninitialized'
            disk_status_detail = ''
            disk_alba_backend_guid = ''
            if disk['available'] is False:
                osd = _info.get('osd')
                disk_alba_state = disk['state']['state']
                if disk_alba_state == 'ok':
                    if osd is None:
                        disk_status = 'initialized'
                    elif osd['id'] is None:
                        alba_id = osd['alba_id']
                        if alba_id is None:
                            disk_status = 'available'
                        else:
                            disk_status = 'unavailable'
                            alba_backend = alba_backend_map.get(alba_id)
                            if alba_backend is not None:
                                disk_alba_backend_guid = alba_backend.guid
                    else:
                        disk_status = 'error'
                        disk_status_detail = 'communicationerror'
                        disk_alba_backend_guid = self.guid

                        for asd in _node.asds:
                            if asd.asd_id == disk['asd_id'] and asd.statistics != {}:
                                disk_status = 'warning'
                                disk_status_detail = 'recenterrors'

                                read = osd['read'] or [0]
                                write = osd['write'] or [0]
                                errors = osd['errors']
                                if len(errors) == 0 or (len(read + write) > 0 and max(min(read), min(write)) > max(error[0] for error in errors) + 300):
                                    disk_status = 'claimed'
                                    disk_status_detail = ''
                elif disk_alba_state == 'decommissioned':
                    disk_status = 'unavailable'
                    disk_status_detail = 'decommissioned'
                else:
                    disk_status = 'error'
                    disk_status_detail = disk['state']['detail']
                    alba_backend = alba_backend_map.get(osd.get('alba_id'))
                    if alba_backend is not None:
                        disk_alba_backend_guid = alba_backend.guid
            disk['status'] = disk_status
            disk['status_detail'] = disk_status_detail
            disk['alba_backend_guid'] = disk_alba_backend_guid
            _disks.append(disk)

        def worker(_queue, _disks):
            while True:
                try:
                    item = _queue.get(False)
                    process_disk(item['info'], _disks, item['node'])
                except Empty:
                    return

        queue = Queue()
        for node in alba_nodes:
            for info in node_disk_map[node.node_id]:
                queue.put({'info': info,
                           'node': node})
        disks = []
        threads = []
        for i in range(5):
            thread = Thread(target=worker, args=(queue, disks))
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()
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
            if not asd_stats:
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

    def _ns_data(self):
        """
        Loads namespace data
        """
        config = 'etcd://127.0.0.1:2379/ovs/arakoon/{0}-abm/config'.format(self.backend.name)
        return AlbaCLI.run('show-namespaces', config=config, extra_params=['--max=-1'], as_json=True)[1]

    def _ns_statistics(self):
        """
        Returns a list of the ASDs namespaces
        """
        # Collect ALBA related statistics
        alba_dataset = {}
        for namespace in self.ns_data:
            if namespace['namespace']['state'] != 'active':
                continue
            alba_dataset[namespace['name']] = namespace['statistics']
        # Collect vPool/vDisk data
        vdisk_dataset = {}
        for vpool in VPoolList.get_vpools():
            if vpool not in vdisk_dataset:
                vdisk_dataset[vpool] = []
            for vdisk in vpool.vdisks:
                vdisk_dataset[vpool].append(vdisk.volume_id)

        # Load disk statistics
        def load_disks(_node, _dict):
            for _asd in _node.all_disks:
                if 'asd_id' in _asd and _asd['asd_id'] in asds and 'usage' in _asd:
                    _dict['size'] += _asd['usage']['size']
                    _dict['used'] += _asd['usage']['used']

        global_usage = {'size': 0,
                        'used': 0}
        nodes = set()
        asds = []
        for asd in self.asds:
            asds.append(asd.asd_id)
            if asd.alba_node not in nodes:
                nodes.add(asd.alba_node)
        threads = []
        for node in nodes:
            thread = Thread(target=load_disks, args=(node, global_usage))
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()

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
        config = 'etcd://127.0.0.1:2379/ovs/arakoon/{0}-abm/config'.format(self.backend.name)
        presets = AlbaCLI.run('list-presets', config=config, as_json=True)
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
        for namespace in self.ns_data:
            if namespace['namespace']['state'] != 'active':
                continue
            policy_usage = namespace['statistics']['bucket_count']
            preset = preset_dict[namespace['namespace']['preset_name']]
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

    def _metadata_information(self):
        """
        Returns metadata information about the backend
        """
        from ovs.dal.hybrids.diskpartition import DiskPartition
        from ovs.dal.lists.servicetypelist import ServiceTypeList

        info = {'nsm_partition_guids': []}

        nsm_service_name = self.backend.name + "-nsm_0"
        nsm_service_type = ServiceTypeList.get_by_name('NamespaceManager')
        for service in nsm_service_type.services:
            if service.name == nsm_service_name:
                for disk in service.storagerouter.disks:
                    for partition in disk.partitions:
                        if DiskPartition.ROLES.DB in partition.roles:
                            info['nsm_partition_guids'].append(partition.guid)
        return info
