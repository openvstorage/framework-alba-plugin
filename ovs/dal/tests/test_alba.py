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
Basic test module
"""
import copy
import time
import requests
import unittest
from ovs.dal.hybrids.albaosd import AlbaOSD
from ovs.dal.tests.alba_helpers import AlbaDalHelper
from ovs.extensions.plugins.tests.alba_mockups import ManagerClientMockup, VirtualAlbaBackend


class Alba(unittest.TestCase):
    """
    The basic unittestsuite will test all basic functionality of the DAL framework
    It will also try accessing all dynamic properties of all hybrids making sure
    that code actually works. This however means that all loaded 3rd party libs
    need to be mocked
    """

    def setUp(self):
        """
        (Re)Sets the stores on every test
        """
        AlbaDalHelper.setup(fake_sleep=True)

    def tearDown(self):
        """
        Clean up the unittest
        """
        AlbaDalHelper.teardown(fake_sleep=True)

    def test_asd_statistics(self):
        """
        Validates whether the ASD statistics work as expected.
        * Add keys that were not passed in
        * Collapse certain keys
        * Calculate correct per-second, average, total, min and max values
        """
        structure = AlbaDalHelper.build_dal_structure({
            'alba_backends': [[1, 'LOCAL']],
            'alba_abm_clusters': [1],
            'alba_nsm_clusters': [(1, 1)],  # (<abackend_id>, <amount_of_nsm_clusters>)
            'alba_nodes': [1],
            'alba_osds': [(1, 1, 1, 1)]  # (<osd_id>, <abackend_id>, <anode_id> <slot_id>)
        })
        osd = structure['alba_osds'][1]
        base_time = time.time()

        expected_0 = {'statistics': {'max': 0, 'n_ps': 0, 'min': 0, 'avg': 0, 'n': 0},
                      'range': {'max': 0, 'n_ps': 0, 'min': 0, 'avg': 0, 'n': 0},
                      'range_entries': {'max': 0, 'n_ps': 0, 'min': 0, 'avg': 0, 'n': 0},
                      'multi_get': {'max': 10, 'n_ps': 0, 'min': 1, 'avg': 13, 'n': 5},
                      'apply': {'max': 5, 'n_ps': 0, 'min': 5, 'avg': 5, 'n': 1},
                      'timestamp': None}
        expected_1 = {'statistics': {'max': 0, 'n_ps': 0, 'min': 0, 'avg': 0, 'n': 0},
                      'range': {'max': 0, 'n_ps': 0, 'min': 0, 'avg': 0, 'n': 0},
                      'range_entries': {'max': 0, 'n_ps': 0, 'min': 0, 'avg': 0, 'n': 0},
                      'multi_get': {'max': 10, 'n_ps': 1, 'min': 1, 'avg': 12.5, 'n': 10},
                      'apply': {'max': 5, 'n_ps': 0, 'min': 5, 'avg': 5, 'n': 1},
                      'timestamp': None}

        VirtualAlbaBackend.statistics = {'alba_osd_1': {'success': True,
                                                        'result': {'Apply': {'n': 1, 'avg': 5, 'min': 5, 'max': 5},
                                                                   'MultiGet': {'n': 2, 'avg': 10, 'min': 5, 'max': 10},
                                                                   'MultiGet2': {'n': 3, 'avg': 15, 'min': 1, 'max': 5}}}}
        statistics = osd._statistics(AlbaOSD._dynamics[0])
        expected_0['timestamp'] = base_time
        self.assertDictEqual(statistics, expected_0, 'The first statistics should be as expected: {0} vs {1}'.format(statistics, expected_0))
        time.sleep(5)
        VirtualAlbaBackend.statistics = {'alba_osd_1': {'success': True,
                                                        'result': {'Apply': {'n': 1, 'avg': 5, 'min': 5, 'max': 5},
                                                                   'MultiGet': {'n': 5, 'avg': 10, 'min': 5, 'max': 10},
                                                                   'MultiGet2': {'n': 5, 'avg': 15, 'min': 1, 'max': 5}}}}
        statistics = osd._statistics(AlbaOSD._dynamics[0])
        expected_1['timestamp'] = base_time + 5
        self.assertDictEqual(statistics, expected_1, 'The second statistics should be as expected: {0} vs {1}'.format(statistics, expected_1))

    def test_node_stack(self):
        # alba backend local stack is derived from the node stack. Testing this one instead
        self.maxDiff = None
        structure = AlbaDalHelper.build_dal_structure({
            'alba_backends': [[1, 'LOCAL']],
            'alba_abm_clusters': [1],
            'alba_nsm_clusters': [(1, 1)],  # (<abackend_id>, <amount_of_nsm_clusters>)
            'alba_nodes': [1],
        })
        node = structure['alba_nodes'][1]
        alba_backend = structure['alba_backends'][1]
        VirtualAlbaBackend.data['backend_1-abm'] = {}
        VirtualAlbaBackend.data['backend_1-abm']['osds'] = []

        # Validate local_stack when the node is alive, but not returning any data
        ManagerClientMockup.test_exceptions[node] = {}
        ManagerClientMockup.test_results[node].update({'get_stack': {}})

        expected = {}
        node.invalidate_dynamics()
        self.assertDictEqual(node._stack(), expected)

        # Validate local_stack when the node is offline
        ManagerClientMockup.test_exceptions[node] = {'get_stack': requests.ConnectionError('test'),
                                                     'get_metadata': requests.ConnectionError('test')}
        ManagerClientMockup.test_results[node] = {'get_stack': {},
                                                  'get_metadata': {}}
        expected = {}
        node.invalidate_dynamics()
        self.assertDictEqual(node._stack(), expected)

        # Validate uninitialized disks
        def _move(info):
            for move in [('state', 'status'),
                         ('state_detail', 'status_detail')]:
                if move[0] in info:
                    info[move[1]] = info.pop(move[0])
        ManagerClientMockup.test_exceptions[node] = {}
        # Asd manager return value
        asd_manager_stack = {'get_stack': {'alba_slot_1': {'aliases': ['/dev/disk/by-path/pci-0000:00:01.0-ata-1'],
                                                           'available': True,
                                                           'device': '/dev/disk/by-id/alba_disk_1',
                                                           'mountpoint': None,
                                                           'node_id': node.node_id,
                                                           'osds': {},
                                                           'partition_aliases': [],
                                                           'partition_amount': 0,
                                                           'size': 1024 ** 3,
                                                           'state': 'empty',
                                                           'state_detail': '',
                                                           'usage': {}}},
                             'get_metadata': {'_version': 3}}
        ManagerClientMockup.test_results[node] = asd_manager_stack
        # Create a copy of the asd-manager return value to mutate it into the expected values for the node.stack
        expected_stack = copy.deepcopy(asd_manager_stack)['get_stack']['alba_slot_1']
        _move(expected_stack)  # Change state -> status and state_detail -> status_detail as this is what the node.stack will return
        expected = {'alba_slot_1': expected_stack}
        node.invalidate_dynamics()
        self.assertDictEqual(node._stack(), expected)

        # Validate initialized disks
        # Initialized disks mean that asds have been created.
        # Update asd-manager stack
        asd_manager_osd_stack = {'asd_id': 'alba_osd_1',
                                 'osd_id': 'alba_osd_1',
                                 'metadata': None,
                                 'capacity': 1024 ** 3,
                                 'folder': 'alba_osd_1',
                                 'home': '/mnt/alba-asd/disk-1/alba_osd_1',
                                 'ips': ['127.0.0.1'],
                                 'log_level': 'info',
                                 'multicast': None,
                                 'node_id': 'node_1',
                                 'port': 35001,
                                 'rocksdb_block_cache_size': 8 * 1024 ** 2,
                                 'state': 'ok',
                                 'transport': 'tcp',
                                 'type': 'ASD'}
        asd_manager_stack_changes = {'available': False,
                                     'mountpoint': '/mnt/alba-asd/asd_1',
                                     'state': 'ok',
                                     'partition_amount': 1,
                                     'partition_aliases': ['/dev/disk/by-id/alba_disk_1_partition_1'],
                                     'osds': {'alba_osd_1': asd_manager_osd_stack},
                                     'usage': {'available': 1024 ** 3 - 1024,
                                               'size': 1024 ** 3,
                                               'used': 1024}}
        ManagerClientMockup.test_results[node]['get_stack']['alba_slot_1'].update(asd_manager_stack_changes)

        # Change the asd-manager stack to what we expect in the node.stack
        expected_updated_osds = copy.deepcopy(asd_manager_osd_stack)
        _move(expected_updated_osds)  # Map state <-> status
        expected_values_stack = copy.deepcopy(asd_manager_stack_changes)
        _move(expected_values_stack)  # Map state <-> status

        # Additional changes to node.stack which are not returned by the asd-manager
        expected_updated_osds.update({'claimed_by': None})  # Osd not in model and is not claimed no None
        expected_values_stack['osds']['alba_osd_1'] = expected_updated_osds

        expected['alba_slot_1'].update(expected_values_stack)
        node.invalidate_dynamics()
        self.assertDictEqual(node._stack(), expected)

        # Validate initialized disk but node is offline
        # The asd manager is not returning any information and nothing about the initialized disk is stored in the DAL so nothing will be returned
        ManagerClientMockup.test_exceptions[node] = {'get_stack': requests.ConnectionError('test'),
                                                     'get_metadata': requests.ConnectionError('test')}
        node.invalidate_dynamics()
        self.assertDictEqual(node._stack(), {})  # Nothing will be returned so expecting nothing

        # Validate claimed ASD
        ManagerClientMockup.test_exceptions[node] = {}
        # Nothing changes for the client getting the stack
        AlbaDalHelper.build_dal_structure(structure={'alba_osds': [(1, 1, 1, 1)]}, previous_structure=structure)  # Osd enters the model

        # Additional changes to node.stack which are not returned by the asd-manager
        expected_updated_osds.update({'claimed_by': alba_backend.guid,  # Osds in model will be marked as claimed by the linked backends guid
                                      'status': 'ok'})
        expected_values_stack['osds']['alba_osd_1'] = expected_updated_osds
        expected['alba_slot_1'].update(expected_values_stack)

        node.invalidate_dynamics()
        self.assertDictEqual(node._stack(), expected)

        # Validate claimed osds but node is offline
        ManagerClientMockup.test_exceptions[node] = {'get_stack': requests.ConnectionError('test'),
                                                     'get_metadata': requests.ConnectionError('test')}
        # Osds are known in model but the state or other stats cannot be fetch
        expected_updated_osds.update({'claimed_by': alba_backend.guid,  # Osd not in model and is not claimed no None
                                      'status': 'unknown',  # State cannot be queried and will be set to unknown
                                      'status_detail': 'nodedown'})  # Detail will be set to 'nodedown'

        expected_values_stack['osds']['alba_osd_1'] = expected_updated_osds
        expected_values_stack.update({'status': 'unknown',
                                     'status_detail': 'nodedown'})
        expected['alba_slot_1'].update(expected_values_stack)
        # Certain info will get lost because the asd-manager is down
        # state and state_detail would've been moved so ignoring these
        asd_manager_osd_keys = ['log_level', 'node_id', 'home', 'transport', 'asd_id', 'capacity', 'multicast',
                                'folder', 'rocksdb_block_cache_size']
        asd_manager_slot_keys = ['available', 'partition_aliases', 'node_id', 'device', 'mountpoint', 'size',
                                 'partition_amount', 'usage', 'aliases']
        for key in asd_manager_osd_keys:
            expected['alba_slot_1']['osds']['alba_osd_1'].pop(key)
        for key in asd_manager_slot_keys:
            expected['alba_slot_1'].pop(key)
        node.invalidate_dynamics()
        self.assertDictEqual(node._stack(), expected)
