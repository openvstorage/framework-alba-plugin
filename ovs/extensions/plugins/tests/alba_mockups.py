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
from ovs.extensions.db.arakooninstaller import ArakoonClusterConfig


class VirtualAlbaBackend(object):
    """
    A virtual Alba Backend
    """
    data = {}
    run_log = {}
    statistics = None

    @staticmethod
    def _clean():
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

    @staticmethod
    def update_maintenance_config(**kwargs):
        """
        Updates maintenance config
        """
        key = VirtualAlbaBackend._key_from_config(**kwargs)
        data = VirtualAlbaBackend._get_data(**kwargs)
        if 'set-lru-cache-eviction' in kwargs:
            data['lru_cache_eviction'] = kwargs['set-lru-cache-eviction']
            VirtualAlbaBackend.run_log[key].append(['update_maintenance_config', 'set_lru_cache_eviction'])

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
        # Only called when the osd has not been claimed in the unit test
        return None


