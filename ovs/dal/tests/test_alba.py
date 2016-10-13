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
import time
import requests
import unittest
from ovs.dal.hybrids.albaosd import AlbaOSD
from ovs.dal.tests.alba_helpers import Helper
from ovs.extensions.generic import fakesleep
from ovs.extensions.plugins.asdmanager import ASDManagerClient
from ovs.extensions.generic.configuration import Configuration
from ovs.extensions.plugins.tests.alba_mockups import VirtualAlbaBackend
from ovs.extensions.storage.persistentfactory import PersistentFactory
from ovs.extensions.storage.volatilefactory import VolatileFactory


class Alba(unittest.TestCase):
    """
    The basic unittestsuite will test all basic functionality of the DAL framework
    It will also try accessing all dynamic properties of all hybrids making sure
    that code actually works. This however means that all loaded 3rd party libs
    need to be mocked
    """

    @classmethod
    def setUpClass(cls):
        """
        Sets up the unittest, mocking a certain set of 3rd party libraries and extensions.
        This makes sure the unittests can be executed without those libraries installed
        """
        cls.volatile = VolatileFactory.get_client()
        cls.volatile.clean()
        cls.persistent = PersistentFactory.get_client()
        cls.persistent.clean()
        fakesleep.monkey_patch()

    def setUp(self):
        """
        (Re)Sets the stores on every test
        """
        self.volatile.clean()
        self.persistent.clean()
        self.maxDiff = None

    @classmethod
    def tearDownClass(cls):
        """
        Clean up the unittest
        """
        fakesleep.monkey_restore()
        cls.volatile = VolatileFactory.get_client()
        cls.volatile.clean()
        cls.persistent = PersistentFactory.get_client()
        cls.persistent.clean()

    def test_asd_statistics(self):
        """
        Validates whether the ASD statistics work as expected.
        * Add keys that were not passed in
        * Collapse certain keys
        * Calculate correct per-second, average, total, min and max values
        """
        structure = Helper.build_service_structure({
            'alba_backends': [1],
            'alba_nodes': [1],
            'alba_disks': [(1, 1)],  # (<adisk_id>, <anode_id>)
            'alba_osds': [(1, 1, 1)]  # (<osd_id>, <adisk_id>, <abackend_id>)
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

    def test_localstack(self):
        """
        Validates whether the local_stack dynamic returns expected values
        """
        Configuration.set('/ovs/alba/backends/global_gui_error_interval', 1)

        structure = Helper.build_service_structure({
            'alba_backends': [1],
            'alba_nodes': [1]
        })
        node = structure['alba_nodes'][1]
        backend = structure['alba_backends'][1]
        VirtualAlbaBackend.data['backend_1_abm'] = {}
        VirtualAlbaBackend.data['backend_1_abm']['osds'] = []

        # Validate local_stack when the node is alive, but not returning any data
        ASDManagerClient.test_exceptions[node] = {}
        ASDManagerClient.test_results[node] = {'get_disks': {},
                                               'get_asds': {}}
        expected = {'node_1': {}}
        node.invalidate_dynamics()
        self.assertDictEqual(backend._local_stack(), expected)

        # Validate local_stack when the node is offline
        ASDManagerClient.test_exceptions[node] = {'get_disks': requests.ConnectionError('test'),
                                                  'get_asds': requests.ConnectionError('test')}
        ASDManagerClient.test_results[node] = {'get_disks': {'alba_disk_1': {'available': True,
                                                                             'device': '/dev/disk/by-id/alba_disk_1',
                                                                             'name': 'alba_disk_1',
                                                                             'node_id': node.node_id,
                                                                             'state': 'ok'}},
                                               'get_asds': {}}
        expected = {'node_1': {}}
        node.invalidate_dynamics()
        self.assertDictEqual(backend._local_stack(), expected)

        # Validate uninitialized disks
        ASDManagerClient.test_exceptions[node] = {}
        expected = {'node_1': {'alba_disk_1': {'asds': {},
                                               'available': True,
                                               'device': '/dev/disk/by-id/alba_disk_1',
                                               'name': 'alba_disk_1',
                                               'node_id': 'node_1',
                                               'state': 'ok',
                                               'status': 'uninitialized',
                                               'status_detail': ''}}}
        node.invalidate_dynamics()
        self.assertDictEqual(backend._local_stack(), expected)

        # Validate initialized disks
        ASDManagerClient.test_results[node]['get_disks']['alba_disk_1'].update({'available': False,
                                                                                'mountpoint': '/mnt/alba-asd/disk-1'})
        expected['node_1']['alba_disk_1'].update({'mountpoint': '/mnt/alba-asd/disk-1',
                                                  'available': False,
                                                  'status': 'initialized'})
        node.invalidate_dynamics()
        self.assertDictEqual(backend._local_stack(), expected)

        # Validate running but not claimed ASD
        ASDManagerClient.test_results[node]['get_disks']['alba_disk_1'].update({'asds': {'alba_osd_1': {'asd_id': 'alba_osd_1',
                                                                                                        'capacity': 1024 ** 3,
                                                                                                        'home': '/mnt/alba-asd/disk-1/alba_osd_1',
                                                                                                        'log_level': 'info',
                                                                                                        'node_id': 'node_1',
                                                                                                        'port': 10000,
                                                                                                        'rocksdb_block_cache_size': 8 * 1024 ** 2,
                                                                                                        'state': 'ok',
                                                                                                        'transport': 'tcp'}}})
        expected['node_1']['alba_disk_1'].update({'mountpoint': '/mnt/alba-asd/disk-1',
                                                  'available': False,
                                                  'status': 'initialized',
                                                  'asds': {'alba_osd_1': {'asd_id': 'alba_osd_1',
                                                                          'capacity': 1024 ** 3,
                                                                          'home': '/mnt/alba-asd/disk-1/alba_osd_1',
                                                                          'log_level': 'info',
                                                                          'node_id': 'node_1',
                                                                          'port': 10000,
                                                                          'rocksdb_block_cache_size': 8 * 1024 ** 2,
                                                                          'state': 'ok',
                                                                          'transport': 'tcp'}}})
        ASDManagerClient.test_exceptions[node] = {}
        node.invalidate_dynamics()
        self.assertDictEqual(backend._local_stack(), expected)

        # Validate with claimed OSD
        VirtualAlbaBackend.data['backend_1_abm']['osds'] = [{'node_id': 'node_1',
                                                             'long_id': 'alba_osd_1',
                                                             'id': 1,
                                                             'read': [],
                                                             'write': [],
                                                             'errors': []}]
        structure = Helper.build_service_structure({
            'alba_disks': [(1, 1)],
            'alba_osds': [(1, 1, 1)]
        }, structure)
        disk = structure['alba_disks'][1]
        osd = structure['alba_osds'][1]
        expected['node_1']['alba_disk_1'].update({'guid': disk.guid,
                                                  'aliases': disk.aliases})
        expected['node_1']['alba_disk_1']['asds']['alba_osd_1'].update({'alba_backend_guid': backend.guid,
                                                                        'status': 'claimed',
                                                                        'status_detail': '',
                                                                        'transport': 'tcp',
                                                                        'guid': osd.guid})
        node.invalidate_dynamics()
        self.assertDictEqual(backend._local_stack(), expected)

        # Oops, it's offline again
        ASDManagerClient.test_exceptions[node] = {'get_disks': requests.ConnectionError('test'),
                                                  'get_asds': requests.ConnectionError('test')}
        expected = {'node_1': {'alba_disk_1': {'status': 'error',
                                               'name': 'alba_disk_1',
                                               'status_detail': 'nodedown',
                                               'guid': disk.guid,
                                               'aliases': disk.aliases,
                                               'asds': {'alba_osd_1': {'asd_id': 'alba_osd_1',
                                                                       'status': 'error',
                                                                       'status_detail': 'nodedown',
                                                                       'alba_backend_guid': backend.guid,
                                                                       'guid': osd.guid}}}}}
        node.invalidate_dynamics()
        self.assertDictEqual(backend._local_stack(), expected)
