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
import copy
import time
from threading import Lock, Thread
from ovs.dal.dataobject import DataObject
from ovs.dal.hybrids.backend import Backend
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs.dal.structures import Property, Relation, Dynamic
from ovs_extensions.api.client import ForbiddenException, NotFoundException, OVSClient
from ovs.extensions.generic.configuration import Configuration
from ovs.extensions.plugins.albacli import AlbaCLI
from ovs.log.log_handler import LogHandler


class AlbaBackend(DataObject):
    """
    The AlbaBackend provides ALBA specific information
    """
    SCALINGS = DataObject.enumerator('Scaling', ['GLOBAL', 'LOCAL'])
    STATUSES = DataObject.enumerator('Status', {'UNKNOWN': 'unknown',
                                                'FAILURE': 'failure',
                                                'WARNING': 'warning',
                                                'RUNNING': 'running'})  # lower-case values for backwards compatibility

    _logger = LogHandler.get('dal', 'albabackend', False)
    __properties = [Property('alba_id', str, mandatory=False, indexed=True, doc='ALBA internal identifier'),
                    Property('scaling', SCALINGS.keys(), doc='Scaling for an ALBA Backend can be {0}'.format(' or '.join(SCALINGS.keys())))]
    __relations = [Relation('backend', Backend, 'alba_backend', onetoone=True, doc='Linked generic Backend')]
    __dynamics = [Dynamic('local_stack', dict, 15, locked=True),
                  Dynamic('statistics', dict, 5, locked=True),
                  Dynamic('ns_data', list, 60, locked=True),
                  Dynamic('usages', dict, 60, locked=True),
                  Dynamic('presets', list, 60, locked=True),
                  Dynamic('available', bool, 60),
                  Dynamic('name', str, 3600),
                  Dynamic('asd_statistics', dict, 5, locked=True),
                  Dynamic('linked_backend_guids', set, 30, locked=True),
                  Dynamic('remote_stack', dict, 60, locked=True),
                  Dynamic('local_summary', dict, 15, locked=True),
                  Dynamic('live_status', str, 30, locked=True)]

    def _local_stack(self):
        """
        Returns a live list of all disks known to this AlbaBackend
        """
        from ovs.dal.lists.albabackendlist import AlbaBackendList

        if self.abm_cluster is None:
            return {}  # No ABM cluster yet, so backend not fully installed yet

        alba_backend_map = {}
        for alba_backend in AlbaBackendList.get_albabackends():
            alba_backend_map[alba_backend.alba_id] = alba_backend

        # Load information based on the model
        asd_map = {}
        storage_map = {}
        alba_nodes = AlbaNodeList.get_albanodes()
        for node in alba_nodes:
            node_id = node.node_id
            storage_map[node_id] = {}
            for disk in node.disks:
                disk_id = disk.aliases[0].split('/')[-1]
                storage_map[node_id][disk_id] = {'asds': {},
                                                 'name': disk_id,
                                                 'guid': disk.guid,
                                                 'status': 'error',
                                                 'aliases': disk.aliases,
                                                 'status_detail': 'unknown'}
                for osd in disk.osds:
                    osd_id = osd.osd_id
                    data = {'asd_id': osd_id,
                            'guid': osd.guid,
                            'status': 'error',
                            'status_detail': 'unknown',
                            'alba_backend_guid': osd.alba_backend_guid}
                    asd_map[osd_id] = data
                    storage_map[node_id][disk_id]['asds'][osd_id] = data

        # Load information from node
        def _load_live_info(_node, _node_data):
            _data = _node.storage_stack
            if _data['status'] != 'ok':
                for disk_entry in _node_data.values():
                    disk_entry['status_detail'] = _data['status']
                    for entry in disk_entry.get('asds', {}).values():
                        entry['status_detail'] = _data['status']
            else:
                for _disk_id, disk_asd_info in _data['stack'].iteritems():
                    if _disk_id not in _node_data:
                        _node_data[_disk_id] = {'asds': {}}
                    entry = _node_data[_disk_id]
                    disk_info = copy.deepcopy(disk_asd_info)
                    del disk_info['asds']
                    entry.update(disk_info)
                    asds_info = disk_asd_info['asds']
                    for _asd_id, asd_info in asds_info.iteritems():
                        if _asd_id not in _node_data[_disk_id]['asds']:
                            _node_data[_disk_id]['asds'][_asd_id] = asd_info
                        else:
                            _node_data[_disk_id]['asds'][_asd_id].update(asd_info)

        threads = []
        for node in alba_nodes:
            thread = Thread(target=_load_live_info, args=(node, storage_map[node.node_id]))
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
        if Configuration.exists(backend_interval_key):
            interval = Configuration.get(backend_interval_key)
        else:
            interval = Configuration.get('/ovs/alba/backends/global_gui_error_interval')
        config = Configuration.get_configuration_path(self.abm_cluster.config_location)
        asds = {}
        for found_osd in AlbaCLI.run(command='list-all-osds', config=config):
            asds[found_osd['long_id']] = found_osd
        for node_data in storage_map.values():
            for _disk in node_data.values():
                for asd_id, asd_data in _disk['asds'].iteritems():
                    if asd_id not in asds:
                        continue
                    found_osd = asds[asd_id]
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
        if self.abm_cluster is None:
            return []  # No ABM cluster yet, so backend not fully installed yet

        config = Configuration.get_configuration_path(self.abm_cluster.config_location)
        return AlbaCLI.run(command='show-namespaces', config=config, named_params={'max': -1})[1]

    def _usages(self):
        """
        Returns an overview of free space, total space and used space
        """
        # Collect total usage
        total_size = 0.0
        total_used = 0.0
        for stats in self.asd_statistics.values():
            total_size += stats['capacity']
            total_used += stats['disk_usage']

        return {'free': total_size - total_used,
                'size': total_size,
                'used': total_used}

    def _presets(self):
        """
        Returns the policies active on the node
        """
        if self.abm_cluster is None:
            return []  # No ABM cluster yet, so backend not fully installed yet

        asds = {}
        if self.scaling != AlbaBackend.SCALINGS.GLOBAL:
            for node in AlbaNodeList.get_albanodes():
                asds[node.node_id] = 0
                for disk in self.local_stack[node.node_id].values():
                    for asd_info in disk['asds'].values():
                        if asd_info['status'] in ['claimed', 'warning']:
                            asds[node.node_id] += 1
        config = Configuration.get_configuration_path(self.abm_cluster.config_location)
        presets = AlbaCLI.run(command='list-presets', config=config)
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
                available_disks = 0
                if self.scaling != AlbaBackend.SCALINGS.GLOBAL:
                    available_disks += sum(min(asds[node], policy[3]) for node in asds)
                if self.scaling != AlbaBackend.SCALINGS.LOCAL:
                    available_disks += sum(self.local_summary['devices'].values())
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
        Returns True if the Backend can be used
        """
        return self.backend.status == 'RUNNING'

    def _name(self):
        """
        Returns the Backend's name
        """
        return self.backend.name

    def _asd_statistics(self):
        """
        Loads statistics from all it's asds in one call
        """
        from ovs.dal.hybrids.albaosd import AlbaOSD

        statistics = {}
        if self.abm_cluster is None:
            return statistics  # No ABM cluster yet, so backend not fully installed yet

        asd_ids = [osd.osd_id for osd in self.osds if osd.osd_type == AlbaOSD.OSD_TYPES.ASD]
        if len(asd_ids) == 0:
            return statistics

        try:
            config = Configuration.get_configuration_path(self.abm_cluster.config_location)
            raw_statistics = AlbaCLI.run(command='asd-multistatistics', config=config, named_params={'long-id': ','.join(asd_ids)})
        except RuntimeError:
            return statistics
        for asd_id, stats in raw_statistics.iteritems():
            if stats['success'] is True:
                statistics[asd_id] = stats['result']
        return statistics

    def _linked_backend_guids(self):
        """
        Returns a list (recursively) of all ALBA backends linked to this ALBA Backend based on the linked AlbaOSDs
        :return: List of ALBA Backend guids
        :rtype: set
        """
        # Import here to prevent from circular references
        from ovs.dal.hybrids.albaosd import AlbaOSD

        def _load_backend_info(_connection_info, _alba_backend_guid, _exceptions):
            # '_exceptions' must be an immutable object to be usable outside the Thread functionality
            client = OVSClient(ip=_connection_info['host'],
                               port=_connection_info['port'],
                               credentials=(_connection_info['username'], _connection_info['password']),
                               version=3)

            try:
                new_guids = client.get('/alba/backends/{0}/'.format(_alba_backend_guid),
                                       params={'contents': 'linked_backend_guids'})['linked_backend_guids']
                with lock:
                    guids.update(new_guids)
            except NotFoundException:
                pass  # ALBA Backend has been deleted, we don't care we can't find the linked guids
            except ForbiddenException as fe:
                AlbaBackend._logger.exception('Collecting remote ALBA Backend information failed due to permission issues. {0}'.format(fe))
                _exceptions.append('not_allowed')
            except Exception as ex:
                AlbaBackend._logger.exception('Collecting remote ALBA Backend information failed with error: {0}'.format(ex))
                _exceptions.append('unknown')

        lock = Lock()
        guids = {self.guid}
        threads = []
        exceptions = []
        for osd in self.osds:
            if osd.osd_type == AlbaOSD.OSD_TYPES.ALBA_BACKEND and osd.metadata is not None:
                connection_info = osd.metadata['backend_connection_info']
                alba_backend_guid = osd.metadata['backend_info']['linked_guid']
                thread = Thread(target=_load_backend_info, args=(connection_info, alba_backend_guid, exceptions))
                thread.start()
                threads.append(thread)
        for thread in threads:
            thread.join()

        if len(exceptions) > 0:
            return None  # This causes the 'Link Backend' button in the GUI to become disabled
        return guids

    def _remote_stack(self):
        """
        Live list of information about remote linked OSDs of type ALBA Backend
        :return: Information about all linked OSDs
        :rtype: dict
        """
        # Import here to prevent from circular references
        from ovs.dal.hybrids.albaosd import AlbaOSD

        def _load_backend_info(_connection_info, _alba_backend_guid):
            client = OVSClient(ip=_connection_info['host'],
                               port=_connection_info['port'],
                               credentials=(_connection_info['username'], _connection_info['password']),
                               version=3)

            return_value[_alba_backend_guid]['live_status'] = AlbaBackend.STATUSES.UNKNOWN
            try:
                info = client.get('/alba/backends/{0}/'.format(_alba_backend_guid),
                                  params={'contents': 'local_summary,live_status'})
                with lock:
                    return_value[_alba_backend_guid].update(info['local_summary'])
                    return_value[_alba_backend_guid]['live_status'] = info['live_status']
            except NotFoundException:
                return_value[_alba_backend_guid]['error'] = 'backend_deleted'
                return_value[_alba_backend_guid]['live_status'] = AlbaBackend.STATUSES.FAILURE
            except ForbiddenException:
                return_value[_alba_backend_guid]['error'] = 'not_allowed'
            except Exception as ex:
                return_value[_alba_backend_guid]['error'] = 'unknown'
                AlbaBackend._logger.exception('Collecting remote ALBA Backend information failed with error: {0}'.format(ex))

        # Retrieve local summaries of all related OSDs of type ALBA_BACKEND
        lock = Lock()
        threads = []
        return_value = {}
        cluster_ips = [sr.ip for sr in StorageRouterList.get_storagerouters()]
        for osd in self.osds:
            if osd.osd_type == AlbaOSD.OSD_TYPES.ALBA_BACKEND and osd.metadata is not None:
                backend_info = osd.metadata['backend_info']
                connection_info = osd.metadata['backend_connection_info']
                connection_host = connection_info['host']
                alba_backend_guid = backend_info['linked_guid']
                return_value[alba_backend_guid] = {'name': backend_info['linked_name'],
                                                   'error': '',
                                                   'domain': None if osd.domain is None else {'guid': osd.domain_guid,
                                                                                              'name': osd.domain.name},
                                                   'preset': backend_info['linked_preset'],
                                                   'osd_id': backend_info['linked_alba_id'],
                                                   'local_ip': connection_host in cluster_ips,
                                                   'remote_host': connection_host}
                thread = Thread(target=_load_backend_info, args=(connection_info, alba_backend_guid))
                thread.start()
                threads.append(thread)

        for thread in threads:
            thread.join()
        return return_value

    def _local_summary(self):
        """
        A local summary for an ALBA Backend containing information used to show in the GLOBAL ALBA Backend detail page
        :return: Information about used size, devices, name, scaling
        :rtype: dict
        """
        usage_info = {'size': 0,
                      'used': 0}
        device_info = {'red': 0,
                       'green': 0,
                       'orange': 0}
        return_value = {'name': self.name,
                        'sizes': usage_info,
                        'devices': device_info,
                        'scaling': self.scaling,
                        'domain_info': dict((backend_domain.domain_guid, backend_domain.domain.name) for backend_domain in self.backend.domains),
                        'backend_guid': self.backend.guid}

        # Calculate device information
        if self.scaling != AlbaBackend.SCALINGS.GLOBAL:
            for node_values in self.local_stack.itervalues():
                for disk_values in node_values.itervalues():
                    for asd_info in disk_values.get('asds', {}).itervalues():
                        if self.guid == asd_info.get('alba_backend_guid'):
                            status = asd_info.get('status', 'unknown')
                            if status == 'claimed':
                                device_info['green'] += 1
                            elif status == 'warning':
                                device_info['orange'] += 1
                            elif status == 'error':
                                device_info['red'] += 1

            # Calculate used and total size
            for stats in self.asd_statistics.values():
                usage_info['size'] += stats['capacity']
                usage_info['used'] += stats['disk_usage']

        if self.scaling != AlbaBackend.SCALINGS.LOCAL:
            for backend_values in self.remote_stack.itervalues():
                for key, value in backend_values.get('sizes', {}).iteritems():
                    usage_info[key] += value

                devices = backend_values.get('devices')
                if devices is None:
                    continue

                if devices['red'] > 0:
                    device_info['red'] += 1
                elif devices['orange'] > 0:
                    device_info['orange'] += 1
                elif devices['green'] > 0:
                    device_info['green'] += 1

        return return_value

    def _live_status(self):
        """
        Retrieve the live status of the ALBA Backend to be displayed in the 'Backends' page in the GUI based on:
            - Maintenance agents presence
            - Maintenance agents status
            - Disk statuses
        :return: Status as reported by the plugin
        :rtype: str
        """
        if self.backend.status == Backend.STATUSES.INSTALLING:
            return 'installing'

        if self.backend.status == Backend.STATUSES.DELETING:
            return 'deleting'
        
        # Verify failed disks
        devices = self.local_summary['devices']
        if devices['red'] > 0:
            return AlbaBackend.STATUSES.FAILURE

        # Verify remote OSDs
        remote_errors = False
        linked_backend_warning = False
        for remote_info in self.remote_stack.itervalues():
            if remote_info['error'] == 'unknown' or remote_info['live_status'] == AlbaBackend.STATUSES.FAILURE:
                return AlbaBackend.STATUSES.FAILURE
            if remote_info['error'] == 'not_allowed':
                remote_errors = True
            if remote_info['live_status'] == AlbaBackend.STATUSES.WARNING:
                linked_backend_warning = True

        # Retrieve ASD and maintenance service information
        def _get_node_information(_node):
            for disk in _node.disks:
                for osd in disk.osds:
                    if osd.alba_backend_guid == self.guid:
                        nodes_used_by_this_backend.add(_node)
            try:
                services = _node.maintenance_services
                if self.name in services:
                    for _service_name, _service_status in services[self.name]:
                        services_for_this_backend[_service_name] = _node
                        service_states[_service_name] = _service_status
                        if _node.node_id not in services_per_node:
                            services_per_node[_node.node_id] = 0
                        services_per_node[_node.node_id] += 1
            except:
                pass

        services_for_this_backend = {}
        services_per_node = {}
        service_states = {}
        nodes_used_by_this_backend = set()
        threads = []
        all_nodes = AlbaNodeList.get_albanodes()
        for node in all_nodes:
            thread = Thread(target=_get_node_information, args=(node,))
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()

        zero_services = False
        if len(services_for_this_backend) == 0:
            if len(all_nodes) > 0:
                AlbaBackend._logger.error('Live status for backend {0} is "failure": no maintenance services'.format(self.name))
                return AlbaBackend.STATUSES.FAILURE
            zero_services = True

        # Verify maintenance agents status
        for service_name, node in services_for_this_backend.iteritems():
            try:
                service_status = service_states.get(service_name)
                if service_status is None or service_status != 'active':
                    AlbaBackend._logger.error('Live status for backend {0} is "failure": non-running maintenance service(s)'.format(self.name))
                    return AlbaBackend.STATUSES.FAILURE
            except:
                pass

        # Verify maintenance agents presence
        layout_key = '/ovs/alba/backends/{0}/maintenance/agents_layout'.format(self.guid)
        layout = None
        if Configuration.exists(layout_key):
            layout = Configuration.get(layout_key)
            if not isinstance(layout, list) or not any(node.node_id for node in all_nodes if node.node_id in layout):
                layout = None

        if layout is None:
            config_key = '/ovs/alba/backends/{0}/maintenance/nr_of_agents'.format(self.guid)
            expected_services = 3
            if Configuration.exists(config_key):
                expected_services = Configuration.get(config_key)
            expected_services = min(expected_services, len(nodes_used_by_this_backend)) or 1
            if len(services_for_this_backend) < expected_services:
                AlbaBackend._logger.warning('Live status for backend {0} is "warning": insufficient maintenance services'.format(self.name))
                return AlbaBackend.STATUSES.WARNING
        else:
            for node_id in layout:
                if node_id not in services_per_node:
                    AlbaBackend._logger.warning('Live status for backend {0} is "warning": invalid maintenance service layout'.format(self.name))
                    return AlbaBackend.STATUSES.WARNING

        # Verify local and remote OSDs
        if devices['orange'] > 0:
            AlbaBackend._logger.warning('Live status for backend {0} is "warning": one or more OSDs in warning'.format(self.name))
            return AlbaBackend.STATUSES.WARNING

        if remote_errors is True or linked_backend_warning is True:
            AlbaBackend._logger.warning('Live status for backend {0} is "warning": errors/warnings on remote stack'.format(self.name))
            return AlbaBackend.STATUSES.WARNING
        if zero_services is True:
            AlbaBackend._logger.warning('Live status for backend {0} is "warning": no maintenance services'.format(self.name))
            return AlbaBackend.STATUSES.WARNING

        return AlbaBackend.STATUSES.RUNNING
