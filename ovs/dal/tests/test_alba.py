#!/usr/bin/env python2
#  Copyright 2014 iNuron NV
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
Basic test module
"""
import sys
from unittest import TestCase
from ovs.dal.tests.alba_mockups import AlbaCLIModule
from ovs.extensions.storage.persistent.dummystore import DummyPersistentStore
from ovs.extensions.storage.volatile.dummystore import DummyVolatileStore
from ovs.extensions.storage.persistentfactory import PersistentFactory
from ovs.extensions.storage.volatilefactory import VolatileFactory


class Alba(TestCase):
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
        # Replace mocked classes
        sys.modules['ovs.extensions.plugins.albacli'] = AlbaCLIModule

        PersistentFactory.store = DummyPersistentStore()
        PersistentFactory.store.clean()
        VolatileFactory.store = DummyVolatileStore()
        VolatileFactory.store.clean()

    @classmethod
    def setUp(cls):
        """
        (Re)Sets the stores on every test
        """
        PersistentFactory.store = DummyPersistentStore()
        PersistentFactory.store.clean()
        VolatileFactory.store = DummyVolatileStore()
        VolatileFactory.store.clean()

    def test_asd_statistics(self):
        """
        Validates whether the ASD statistics work as expected.
        * Add keys that were not passed in
        * Collapse certain keys
        * Calculate correct per-second, average, total, min and max values
        """
        from ovs.extensions.plugins.albacli import AlbaCLI
        from ovs.dal.hybrids.albaasd import AlbaASD
        from ovs.dal.hybrids.albabackend import AlbaBackend
        from ovs.dal.hybrids.backend import Backend
        expected = {'statistics': {'max': 0, 'n_ps': 0, 'min': 0, 'avg': 0, 'n': 0},
                    'range': {'max': 0, 'n_ps': 0, 'min': 0, 'avg': 0, 'n': 0},
                    'range_entries': {'max': 0, 'n_ps': 0, 'min': 0, 'avg': 0, 'n': 0},
                    'multi_get': {'max': 10, 'n_ps': 1.0, 'min': 1, 'avg': 13.0, 'n': 5},
                    'apply': {'max': 5, 'n_ps': 0.2, 'min': 5, 'avg': 5, 'n': 1},
                    'creation': 123,
                    'period': 5}
        AlbaCLI.run_results['asd-statistics'] = {'Apply': {'n': 1, 'avg': 5, 'min': 5, 'max': 5},
                                                 'MultiGet': {'n': 2, 'avg': 10, 'min': 5, 'max': 10},
                                                 'MultiGet2': {'n': 3, 'avg': 15, 'min': 1, 'max': 5},
                                                 'creation' : 123,
                                                 'period': 5}
        asd = AlbaASD()
        asd.alba_backend = AlbaBackend()
        asd.alba_backend.backend = Backend()
        asd.alba_backend.backend.name = 'foobar'
        statistics = asd._statistics()
        self.assertDictEqual(statistics, expected, 'The statistics should be as expected: {0} vs {1}'.format(statistics, expected))


if __name__ == '__main__':
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(Alba)
    unittest.TextTestRunner(verbosity=2).run(suite)
