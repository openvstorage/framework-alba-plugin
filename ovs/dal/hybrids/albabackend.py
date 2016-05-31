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
AlbaBackend module
"""
import time
import requests
import threading
from ovs.dal.dataobject import DataObject
from ovs.dal.hybrids.backend import Backend
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.vpoollist import VPoolList
from ovs.dal.structures import Property, Relation, Dynamic
from ovs.extensions.api.client import OVSClient
from ovs.extensions.db.etcd.configuration import EtcdConfiguration
from ovs.extensions.plugins.albacli import AlbaCLI
from ovs.log.log_handler import LogHandler


class AlbaBackend(DataObject):
    """
    The AlbaBackend provides ALBA specific information
    """
    SCALINGS = DataObject.enumerator('Scaling', ['GLOBAL', 'LOCAL'])

    _logger = LogHandler.get('dal', 'albabackend', False)
    __properties = [Property('alba_id', str, mandatory=False, doc='ALBA internal identifier'),
                    Property('scaling', SCALINGS.keys(), doc='Scaling for an ALBA backend can be {0}'.format(' or '.join(SCALINGS.keys())))]
    __relations = [Relation('backend', Backend, 'alba_backend', onetoone=True, doc='Linked generic backend')]
    __dynamics = [Dynamic('storage_stack', dict, 5),
                  Dynamic('statistics', dict, 5, locked=True),
                  Dynamic('ns_data', list, 60),
                  Dynamic('ns_statistics', dict, 60),
                  Dynamic('presets', list, 60),
                  Dynamic('available', bool, 60),
                  Dynamic('name', str, 3600),
                  Dynamic('metadata_information', dict, 60),
                  Dynamic('asd_statistics', dict, 5, locked=True),
                  Dynamic('linked_backend_guids', set, 30)]

    def _storage_stack(self):
        """
        Returns a live list of all disks known to this AlbaBackend
        """
        from ovs.dal.lists.albanodelist import AlbaNodeList
        from ovs.dal.lists.albabackendlist import AlbaBackendList

        storage_map = {'local': {},
                       'global': {}}

        if len(self.abm_services) == 0:
            return storage_map  # No ABM services yet, so backend not fully installed yet

        asd_map = {}

        alba_backend_map = {}
        for alba_backend in AlbaBackendList.get_albabackends():
            alba_backend_map[alba_backend.alba_id] = alba_backend

        # Load information based on the model
        alba_nodes = AlbaNodeList.get_albanodes()
        for node in alba_nodes:
            node_id = node.node_id
            storage_map['local'][node_id] = {}
            for disk in node.disks:
                disk_id = disk.name
                storage_map['local'][node_id][disk_id] = {'name': disk_id,
                                                          'guid': disk.guid,
                                                          'status': 'error',
                                                          'status_detail': 'unknown',
                                                          'asds': {}}
                for osd in disk.osds:
                    osd_id = osd.osd_id
                    data = {'asd_id': osd_id,
                            'guid': osd.guid,
                            'status': 'error',
                            'status_detail': 'unknown',
                            'alba_backend_guid': osd.alba_backend_guid}
                    asd_map[osd_id] = data
                    storage_map['local'][node_id][disk_id]['asds'][osd_id] = data

        # Load information from node
        def _load_live_info(_node, _node_data):
            # Live disk information
            try:
                disk_data = _node.client.get_disks()
            except (requests.ConnectionError, requests.Timeout):
                for entry in _node_data.values():
                    entry['status_detail'] = 'nodedown'
                disk_data = {}
            for _disk_id, disk_info in disk_data.iteritems():
                if _disk_id in _node_data:
                    entry = _node_data[_disk_id]
                else:
                    entry = {'name': _disk_id,
                             'status': 'unknown',
                             'status_detail': '',
                             'asds': {}}
                    _node_data[_disk_id] = entry
                entry.update(disk_info)
                if disk_info['state'] == 'ok':
                    entry['status'] = 'uninitialized' if disk_info['available'] is True else 'initialized'
                    entry['status_detail'] = ''
                else:
                    entry['status'] = disk_info['state']
                    entry['status_detail'] = disk_info.get('state_detail', '')
            # Live ASD information
            try:
                _asd_data = _node.client.get_asds()
            except (requests.ConnectionError, requests.Timeout):
                for disk_entry in _node_data.values():
                    for entry in disk_entry['asds'].values():
                        entry['status_detail'] = 'nodedown'
                _asd_data = {}
            for _disk_id, asds in _asd_data.iteritems():
                if _disk_id not in _node_data:
                    continue
                for _asd_id, asd_info in asds.iteritems():
                    entry = {'asd_id': _asd_id,
                             'status': 'error' if asd_info['state'] == 'error' else 'initialized',
                             'status_detail': asd_info.get('state_detail', ''),
                             'state': asd_info['state'],
                             'state_detail': asd_info.get('state_detail', '')}
                    if _asd_id not in _node_data[_disk_id]['asds']:
                        _node_data[_disk_id]['asds'][_asd_id] = entry
                        asd_map[_asd_id] = entry
                    else:
                        _node_data[_disk_id]['asds'][_asd_id].update(entry)
        threads = []
        for node in alba_nodes:
            thread = threading.Thread(target=_load_live_info, args=(node, storage_map['local'][node.node_id]))
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()

        # Mix in usage information
        for asd_id, stats in self.asd_statistics.iteritems():
            if asd_id in asd_map:
                asd_map[asd_id]['usage'] = {'size': int(stats['capacity']),
                                            'used': int(stats['disk_usage']),
                                            'available': int(stats['capacity'] - stats['disk_usage'])}

        # Load information from alba
        backend_interval_key = '/ovs/alba/backends/{0}/gui_error_interval'.format(self.guid)
        if EtcdConfiguration.exists(backend_interval_key):
            interval = EtcdConfiguration.get(backend_interval_key)
        else:
            interval = EtcdConfiguration.get('/ovs/alba/backends/global_gui_error_interval')
        config = 'etcd://127.0.0.1:2379/ovs/arakoon/{0}/config'.format(self.abm_services[0].service.name)
        for found_osd in AlbaCLI.run('list-all-osds', config=config, as_json=True):
            node_id = found_osd['node_id']
            asd_id = found_osd['long_id']
            for _disk in storage_map['local'].get(node_id, {}).values():
                asd_data = _disk['asds'].get(asd_id, {})
                if 'state' not in asd_data:
                    continue
                if found_osd.get('decommissioned') is True:
                    asd_data['status'] = 'unavailable'
                    asd_data['status_detail'] = 'decommissioned'
                    continue
                state = asd_data['state']
                if state == 'ok':
                    if found_osd['id'] is None:
                        alba_id = found_osd['alba_id']
                        if alba_id is None:
                            asd_data['status'] = 'available'
                        else:
                            asd_data['status'] = 'unavailable'
                            alba_backend = alba_backend_map.get(alba_id)
                            if alba_backend is not None:
                                asd_data['alba_backend_guid'] = alba_backend.guid
                    else:
                        asd_data['alba_backend_guid'] = self.guid
                        asd_data['status'] = 'warning'
                        asd_data['status_detail'] = 'recenterrors'

                        read = found_osd['read'] or [0]
                        write = found_osd['write'] or [0]
                        errors = found_osd['errors']
                        if len(errors) == 0 or (len(read + write) > 0 and max(min(read), min(write)) > max(error[0] for error in errors) + interval):
                            asd_data['status'] = 'claimed'
                            asd_data['status_detail'] = ''
                else:
                    asd_data['status'] = 'error'
                    asd_data['status_detail'] = asd_data.get('state_detail', '')
                    alba_backend = alba_backend_map.get(found_osd.get('alba_id'))
                    if alba_backend is not None:
                        asd_data['alba_backend_guid'] = alba_backend.guid
        return storage_map

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
        for asd in self.osds:
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
        if len(self.abm_services) == 0:
            return []  # No ABM services yet, so backend not fully installed yet

        config = 'etcd://127.0.0.1:2379/ovs/arakoon/{0}/config'.format(self.abm_services[0].service.name)
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
            vdisk_dataset[vpool] = vpool.storagedriver_client.list_volumes()

        # Collect global usage
        global_usage = {'size': 0,
                        'used': 0}
        for stats in self.asd_statistics.values():
            global_usage['size'] += stats['capacity']
            global_usage['used'] += stats['disk_usage']

        # Cross merge
        dataset = {'global': {'size': global_usage['size'],
                              'used': global_usage['used']},
                   'vpools': {},
                   'overhead': 0,
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
        dataset['overhead'] = max(0, dataset['global']['used'] - dataset['unknown']['storage'] - sum(usage['storage'] for usage in dataset['vpools'].values()))
        return dataset

    def _presets(self):
        """
        Returns the policies active on the node
        """
        if len(self.abm_services) == 0:
            return []  # No ABM services yet, so backend not fully installed yet

        storage_stack = self.storage_stack['local']
        asds = {}
        for node in AlbaNodeList.get_albanodes():
            asds[node.node_id] = 0
            for disk in storage_stack[node.node_id].values():
                for asd_info in disk['asds'].values():
                    if asd_info['status'] in ['claimed', 'warning']:
                        asds[node.node_id] += 1
        config = 'etcd://127.0.0.1:2379/ovs/arakoon/{0}/config'.format(self.abm_services[0].service.name)
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
                available_disks = sum(min(asds[node], policy[3]) for node in asds)
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
        from ovs.dal.hybrids.servicetype import ServiceType
        from ovs.dal.lists.servicetypelist import ServiceTypeList

        info = {'nsm_partition_guids': []}

        nsm_service_name = self.backend.name + "-nsm_0"
        nsm_service_type = ServiceTypeList.get_by_name(ServiceType.SERVICE_TYPES.NS_MGR)
        for service in nsm_service_type.services:
            if service.name == nsm_service_name and service.is_internal is True:
                for disk in service.storagerouter.disks:
                    for partition in disk.partitions:
                        if DiskPartition.ROLES.DB in partition.roles:
                            info['nsm_partition_guids'].append(partition.guid)
        return info

    def _asd_statistics(self):
        """
        Loads statistics from all it's asds in one call
        """
        statistics = {}
        if len(self.abm_services) == 0:
            return statistics  # No ABM services yet, so backend not fully installed yet
        if len(self.osds) == 0:
            return statistics

        asd_ids = [asd.osd_id for asd in self.osds]
        try:
            config = 'etcd://127.0.0.1:2379/ovs/arakoon/{0}/config'.format(self.abm_services[0].service.name)
            raw_statistics = AlbaCLI.run('asd-multistatistics', long_id=','.join(asd_ids), config=config, as_json=True)
        except RuntimeError:
            return statistics
        for asd_id, stats in raw_statistics.iteritems():
            if stats['success'] is True:
                statistics[asd_id] = stats['result']
        return statistics

    def _linked_backend_guids(self):
        """
        Returns a list (recursively) of all ALBA backends linked to this ALBA backend based on the linked AlbaOSDs
        :return: List of ALBA Backend guids
        :rtype: list
        """
        # Import here to prevent from circular references
        from ovs.dal.hybrids.albaosd import AlbaOSD

        def _load_backend_info():
            client = OVSClient(ip=connection_info['host'],
                               port=connection_info['port'],
                               credentials=(connection_info['username'], connection_info['password']))
            with lock:
                try:
                    guids.update(client.get('/alba/backends/{0}/'.format(alba_backend_guid))['linked_backend_guids'])
                except Exception as ex:
                    AlbaBackend._logger.exception('Collecting remote ALBA backend information failed with error: {0}'.format(ex))
                    exceptions.append(ex)

        lock = threading.Lock()
        guids = {self.guid}
        threads = []
        exceptions = []
        for osd in self.osds:
            if osd.osd_type == AlbaOSD.OSD_TYPES.ALBA_BACKEND and osd.metadata is not None:  # In this case osd.osd_id is a guid of an ALBA Backend
                connection_info = osd.metadata['backend_connection_info']
                alba_backend_guid = osd.metadata['backend_info']['linked_guid']
                if connection_info['host'] == '':
                    guids.update(AlbaBackend(alba_backend_guid).linked_backend_guids)
                else:
                    thread = threading.Thread(target=_load_backend_info)
                    thread.start()
                    threads.append(thread)
        for thread in threads:
            thread.join()

        if len(exceptions) > 0:
            raise RuntimeError(exceptions[0])

        return guids
