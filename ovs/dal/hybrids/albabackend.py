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
from threading import Lock, Thread
from ovs.dal.dataobject import DataObject
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.hybrids.backend import Backend
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs.dal.structures import Property, Relation, Dynamic
from ovs_extensions.api.client import OVSClient
from ovs_extensions.api.exceptions import HttpForbiddenException, HttpNotFoundException
from ovs.extensions.generic.configuration import Configuration
from ovs.extensions.generic.logger import Logger
from ovs.extensions.plugins.albacli import AlbaCLI, AlbaError
from ovs.extensions.storage.volatilefactory import VolatileFactory


class AlbaBackend(DataObject):
    """
    The AlbaBackend provides ALBA specific information
    """
    SCALINGS = DataObject.enumerator('Scaling', ['GLOBAL', 'LOCAL'])
    STATUSES = DataObject.enumerator('Status', {'UNKNOWN': 'unknown',
                                                'FAILURE': 'failure',
                                                'WARNING': 'warning',
                                                'RUNNING': 'running'})  # lower-case values for backwards compatibility

    _logger = Logger('hybrids')
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
                  Dynamic('osd_statistics', dict, 5, locked=True),
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

        # Load information from node
        def _load_live_info(_node, _storage_map):
            node_id = _node.node_id
            _storage_map[node_id] = {}
            for slot_id, _slot_data in _node.stack.iteritems():
                # Pre-fill some info
                _storage_map[node_id][slot_id] = {'osds': {},
                                                  'name': slot_id,
                                                  'status': 'error',
                                                  'status_detail': 'unknown'}
                _storage_map[node_id][slot_id].update(_slot_data)

        threads = []
        storage_map = {}
        for node in AlbaNodeList.get_albanodes():
            thread = Thread(target=_load_live_info, args=(node, storage_map))
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()

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
        usages = {'free': 0.0,
                  'size': 0.0,
                  'used': 0.0}

        if self.abm_cluster is None:
            return usages

        config = Configuration.get_configuration_path(self.abm_cluster.config_location)
        try:
            osds_stats = AlbaCLI.run(command='list-osds', config=config)
        except AlbaError:
            self._logger.exception('Unable to fetch OSD information')
            return usages

        for osd_stats in osds_stats:
            usages['size'] += osd_stats['total']
            usages['used'] += osd_stats['used']
        usages['free'] = usages['size'] - usages['used']

        return usages

    def _presets(self):
        """
        Returns the policies active on the node
        """
        if self.abm_cluster is None:
            return []  # No ABM cluster yet, so backend not fully installed yet

        osds = {}
        if self.scaling != AlbaBackend.SCALINGS.GLOBAL:
            for node_id, slots in self.local_stack.iteritems():
                osds[node_id] = 0
                for slot_id, slot_data in slots.iteritems():
                    for osd_id, osd_data in slot_data['osds'].iteritems():
                        if osd_data['status'] in [AlbaNode.OSD_STATUSES.OK, AlbaNode.OSD_STATUSES.WARNING] and osd_data.get('claimed_by') == self.guid:
                            osds[node_id] += 1
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
                if self.scaling == AlbaBackend.SCALINGS.GLOBAL:
                    available_disks += sum(self.local_summary['devices'].values())
                if self.scaling == AlbaBackend.SCALINGS.LOCAL:
                    available_disks += sum(min(osds[node], policy[3]) for node in osds)
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
                used_policy = tuple(usage[0])  # Policy as reported to be "in use"
                for configured_policy in preset['policies']:  # All configured policies
                    if used_policy[0] == configured_policy[0] and used_policy[1] == configured_policy[1] and used_policy[3] <= configured_policy[3]:
                        preset['policy_metadata'][configured_policy]['in_use'] = True
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

    def _osd_statistics(self):
        """
        Loads statistics from all it's asds in one call
        """
        from ovs.dal.hybrids.albaosd import AlbaOSD

        statistics = {}
        if self.abm_cluster is None:
            return statistics  # No ABM cluster yet, so backend not fully installed yet

        osd_ids = [osd.osd_id for osd in self.osds if osd.osd_type in [AlbaOSD.OSD_TYPES.ASD, AlbaOSD.OSD_TYPES.AD]]
        if len(osd_ids) == 0:
            return statistics
        try:
            config = Configuration.get_configuration_path(self.abm_cluster.config_location)
            # TODO: This will need to be changed to osd-multistatistics, see openvstorage/alba#749
            raw_statistics = AlbaCLI.run(command='asd-multistatistics', config=config, named_params={'long-id': ','.join(osd_ids)})
        except RuntimeError:
            return statistics
        for osd_id, stats in raw_statistics.iteritems():
            if stats['success'] is True:
                statistics[osd_id] = stats['result']
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
            client = OVSClient.get_instance(connection_info=_connection_info, cache_store=VolatileFactory.get_client())
            try:
                new_guids = client.get('/alba/backends/{0}/'.format(_alba_backend_guid),
                                       params={'contents': 'linked_backend_guids'})['linked_backend_guids']
                with lock:
                    guids.update(new_guids)
            except HttpNotFoundException:
                pass  # ALBA Backend has been deleted, we don't care we can't find the linked guids
            except HttpForbiddenException as fe:
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
            client = OVSClient.get_instance(connection_info=_connection_info, cache_store=VolatileFactory.get_client())
            return_value[_alba_backend_guid]['live_status'] = AlbaBackend.STATUSES.UNKNOWN
            try:
                info = client.get('/alba/backends/{0}/'.format(_alba_backend_guid),
                                  params={'contents': 'local_summary,live_status'})
                with lock:
                    return_value[_alba_backend_guid].update(info['local_summary'])
                    return_value[_alba_backend_guid]['live_status'] = info['live_status']
            except HttpNotFoundException:
                return_value[_alba_backend_guid]['error'] = 'backend_deleted'
                return_value[_alba_backend_guid]['live_status'] = AlbaBackend.STATUSES.FAILURE
            except HttpForbiddenException:
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
                       'orange': 0,
                       'gray': 0}
        return_value = {'name': self.name,
                        'sizes': usage_info,
                        'devices': device_info,
                        'scaling': self.scaling,
                        'domain_info': dict((backend_domain.domain_guid, backend_domain.domain.name) for backend_domain in self.backend.domains),
                        'backend_guid': self.backend.guid}

        # Calculate device information
        if self.scaling != AlbaBackend.SCALINGS.GLOBAL:
            for node_values in self.local_stack.itervalues():
                for slot_values in node_values.itervalues():
                    for osd_info in slot_values.get('osds', {}).itervalues():
                        if self.guid == osd_info.get('claimed_by'):
                            status = osd_info.get('status', 'unknown')
                            if status == AlbaNode.OSD_STATUSES.OK:
                                device_info['green'] += 1
                            elif status == AlbaNode.OSD_STATUSES.WARNING:
                                device_info['orange'] += 1
                            elif status == AlbaNode.OSD_STATUSES.ERROR:
                                device_info['red'] += 1
                            elif status == AlbaNode.OSD_STATUSES.UNKNOWN:
                                device_info['gray'] += 1

            # Calculate used and total size
            usage_info = self.usages

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
                elif devices.get('gray', 0) > 0:
                    device_info['gray'] += 1

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
            if _node not in nodes_used_by_this_backend:
                for slot_info in _node.stack.itervalues():
                    for osd_info in slot_info['osds'].itervalues():
                        if osd_info['claimed_by'] == self.guid:
                            nodes_used_by_this_backend.add(_node)
                            break
                    if _node in nodes_used_by_this_backend:
                        break

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
