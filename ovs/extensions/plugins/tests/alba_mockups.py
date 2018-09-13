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
Mocks Alba backends
"""
import re
import requests
from ovs.extensions.db.arakooninstaller import ArakoonClusterConfig
from ovs.extensions.plugins.asdmanager import ASDManagerClient


class VirtualAlbaBackend(object):
    """
    A virtual Alba Backend
    """
    MAINTENANCE_CONFIG_KEY = 'maintenance_config'

    data = {}
    run_log = {}
    statistics = None

    @staticmethod
    def clean_data():
        """
        Clean everything related to the ALBA tests
        """
        VirtualAlbaBackend.data = {}
        VirtualAlbaBackend.run_log = {}
        VirtualAlbaBackend.statistics = None

    @staticmethod
    def update_abm_client_config(**kwargs):
        """
        Updates the internal configuration based on external configuration
        """
        key = VirtualAlbaBackend._key_from_config(**kwargs)
        if key not in VirtualAlbaBackend.data:
            VirtualAlbaBackend.data[key] = {'alba-id': key}
            VirtualAlbaBackend.run_log[key] = []
        VirtualAlbaBackend.run_log[key].append(['update_abm_client_config'])

    @staticmethod
    def add_nsm_host(**kwargs):
        """
        Adds an NSM host to the system
        """
        key = VirtualAlbaBackend._key_from_config(**kwargs)
        data = VirtualAlbaBackend._get_data(**kwargs)
        if 'nsms' not in data:
            data['nsms'] = []
        nsm_config_key = kwargs['extra_params'][0]
        nsm = nsm_config_key.split('/')[-2]
        data['nsms'].append({'id': nsm,
                             'namespaces_count': 0,
                             '_config_key': nsm_config_key.split('=')[-1]})
        VirtualAlbaBackend.run_log[key].append(['add_nsm_host', nsm])

    @staticmethod
    def get_alba_id(**kwargs):
        """
        Gets the Alba ID
        """
        data = VirtualAlbaBackend._get_data(**kwargs)
        return {'id': data['alba-id']}

    @staticmethod
    def list_nsm_hosts(**kwargs):
        """
        Lists all nsm hosts
        """
        data = VirtualAlbaBackend._get_data(**kwargs)
        return data['nsms']

    @classmethod
    def update_maintenance_config(cls, **kwargs):
        """
        Updates maintenance config
        """
        action_key_map = {'set-lru-cache-eviction': ('redis_lru_cache_eviction', {}),
                          'enable-auto-cleanup-deleted-namespaces-days': ('auto_cleanup_deleted_namespaces', 30),
                          '--eviction-type-random': ('eviction_type', ['Random'])}
        key = cls._key_from_config(**kwargs)
        data = cls._get_data(**kwargs)
        if cls.MAINTENANCE_CONFIG_KEY not in data:
            data[cls.MAINTENANCE_CONFIG_KEY] = {}
        maintenance_config = data[cls.MAINTENANCE_CONFIG_KEY]
        for action, (maintenance_key, maintenance_value) in action_key_map.iteritems():
            if action in kwargs:
                maintenance_config[maintenance_key] = kwargs[action]
                cls.run_log[key].append(['update_maintenance_config', action])
            if action in kwargs.get('extra_params', []):
                # Special case, take the value from the mapping
                maintenance_config[maintenance_key] = maintenance_value
                cls.run_log[key].append(['update_maintenance_config', action])

    @classmethod
    def get_maintenance_config(cls, **kwargs):
        """
        Return sample maintenance config
        """
        sample_config = {u'auto_cleanup_deleted_namespaces': None,
                         u'auto_repair_disabled_nodes': [],
                         u'auto_repair_timeout_seconds': 900.0,
                         u'cache_eviction_prefix_preset_pairs': {},
                         u'enable_auto_repair': True,
                         u'enable_rebalance': True,
                         u'eviction_type': [u'Automatic'],
                         u'redis_lru_cache_eviction': None}
        sample_config.update(cls._get_data(**kwargs).get(cls.MAINTENANCE_CONFIG_KEY, {}))
        return sample_config

    @staticmethod
    def update_nsm_host(**kwargs):
        """
        Updates the NSM host
        """
        key = VirtualAlbaBackend._key_from_config(**kwargs)
        nsm = kwargs['extra_params'][0].split('/')[-2]
        VirtualAlbaBackend.run_log[key].append(['update_nsm_host', nsm])

    @staticmethod
    def asd_multistatistics(**kwargs):
        """
        Returns statistics
        """
        _ = kwargs
        return VirtualAlbaBackend.statistics

    @staticmethod
    def list_all_osds(**kwargs):
        """
        Lists all osds
        """
        data = VirtualAlbaBackend._get_data(**kwargs)
        return data['osds']

    @staticmethod
    def _get_nsm_state(abm):
        state = {}
        data = VirtualAlbaBackend.data[abm]
        for nsm in data['nsms']:
            config = ArakoonClusterConfig(cluster_id=nsm['id'])
            state[nsm['id']] = [node.name for node in config.nodes]
        return state

    @staticmethod
    def _key_from_config(**kwargs):
        if 'config' not in kwargs:
            raise RuntimeError('Missing config parameter')
        return kwargs['config'].split('/')[-2]

    @staticmethod
    def _get_data(**kwargs):
        key = VirtualAlbaBackend._key_from_config(**kwargs)
        if key not in VirtualAlbaBackend.data:
            raise RuntimeError('Unknown backend: {0}'.format(key))
        return VirtualAlbaBackend.data[key]

    @staticmethod
    def get_osd_claimed_by(*args, **kwargs):
        """
        Check whether an osd is claimed based on ip and port
        :return: Alba id or None
        """
        _ = args
        ip = kwargs.get('host')
        port = kwargs.get('port')
        if ip is None or port is None:
            return None
        return VirtualAlbaBackend.data.get('{0}:{1}'.format(ip, port))


class ManagerClientMockup(ASDManagerClient):
    """
    ASD Manager Client used by the unittests
    """
    test_results = {}
    test_exceptions = {}
    maintenance_agents = {}

    # Map the requests method with the table of the url regex and methodname
    api_method_mapping = {
        requests.get: {re.compile('^$'): 'get_metadata',
                       re.compile('^slots$'): 'get_stack',
                       re.compile('^service_status\/.*$'): 'get_service_status',
                       re.compile('^maintenance$'): 'list_maintenance_services'},
        requests.put: {},
        requests.delete: {},
        requests.patch: {},
        requests.post: {re.compile('^maintenance\/.*\/add$'): 'add_maintenance_service',
                        re.compile('^maintenance\/.*\/remove'): 'remove_maintenance_service'},
    }

    def __init__(self, node):
        super(ManagerClientMockup, self).__init__(node=node)

    @staticmethod
    def clean_data():
        ManagerClientMockup.test_results = {}
        ManagerClientMockup.test_exceptions = {}
        ManagerClientMockup.maintenance_agents = {}

    def _call(self, *args, **kwargs):
        # type: (*any, **any) -> any
        """
        Simulate API calls
        :return: Result of the api call
        :rtype: any
        """
        requests_method = kwargs['method']
        url = kwargs['url']
        data = kwargs['json']
        method_name = self._convert_url_to_method(requests_method, url)
        exception = self.test_exceptions.get(self.node, {}).get(method_name)
        if exception:
            raise exception

        if method_name == 'add_maintenance_service':
            service_name = url.split('/')[1]
            read_preferences = data['read_preferences']
            if self.node not in self.maintenance_agents:
                self.maintenance_agents[self.node] = {}
            self.maintenance_agents[self.node][service_name] = read_preferences
        elif method_name == 'remove_maintenance_service':
            service_name = url.split('/')[1]
            self.maintenance_agents[self.node].pop(service_name, None)
            if len(self.maintenance_agents[self.node]) == 0:
                self.maintenance_agents.pop(self.node)
        elif method_name == 'list_maintenance_services':
            if self.node in self.maintenance_agents:
                return {'services': self.maintenance_agents[self.node].keys()}
            return {'services': []}

        return self.test_results[self.node][method_name]

    @classmethod
    def _convert_url_to_method(cls, requests_method, url):
        # type: (callable, str) -> str
        """
        Converts the given url to a method name
        These method names are used within unittesting instead of urls to keep it simpler
        :return: The method name associated with the url
        """
        possible_methods = cls.api_method_mapping[requests_method]
        for url_regex, method_name in possible_methods.iteritems():
            if url_regex.match(url):
                return method_name
        raise NotImplementedError('No result found for {0} with url {1}'.format(requests_method, url))
