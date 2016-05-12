# Copyright 2016 iNuron NV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Basic test module
"""
import time
import unittest
from ovs.dal.hybrids.albaasd import AlbaASD
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.albadisk import AlbaDisk
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.hybrids.backend import Backend
from ovs.dal.hybrids.backendtype import BackendType
from ovs.dal.hybrids.j_abmservice import ABMService
from ovs.dal.hybrids.service import Service
from ovs.dal.hybrids.servicetype import ServiceType
from ovs.extensions.generic import fakesleep
from ovs.extensions.plugins.albacli import AlbaCLI
from ovs.extensions.plugins.asdmanager import ASDManagerClient
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
        base_time = time.time()
        backend_type = BackendType()
        backend_type.code = 'alba'
        backend_type.name = 'ALBA'
        backend_type.save()
        backend = Backend()
        backend.name = 'foobar'
        backend.backend_type = backend_type
        backend.save()
        alba_backend = AlbaBackend()
        alba_backend.backend = backend
        alba_backend.save()
        alba_node = AlbaNode()
        alba_node.ip = '127.0.0.1'
        alba_node.port = 8500
        alba_node.username = 'foo'
        alba_node.password = 'bar'
        alba_node.node_id = 'foobar'
        alba_node.save()
        alba_disk = AlbaDisk()
        alba_disk.name = 'foo'
        alba_disk.alba_node = alba_node
        alba_disk.save()
        asd = AlbaASD()
        asd.asd_id = 'foo'
        asd.alba_backend = alba_backend
        asd.alba_disk = alba_disk
        asd.save()
        service_type = ServiceType()
        service_type.name = 'AlbaManager'
        service_type.save()
        service = Service()
        service.name = 'foobar'
        service.type = service_type
        service.ports = []
        service.save()
        abm_service = ABMService()
        abm_service.service = service
        abm_service.alba_backend = alba_backend
        abm_service.save()

        asdmanager_client = ASDManagerClient('')
        asdmanager_client._results['get_disks'] = []
        AlbaCLI._run_results['asd-multistatistics'] = {'foo': {'success': True,
                                                               'result': {'Apply': {'n': 1, 'avg': 5, 'min': 5, 'max': 5},
                                                                          'MultiGet': {'n': 2, 'avg': 10, 'min': 5, 'max': 10},
                                                                          'MultiGet2': {'n': 3, 'avg': 15, 'min': 1, 'max': 5}}}}
        statistics = asd._statistics(AlbaASD._dynamics[0])
        expected_0['timestamp'] = base_time
        self.assertDictEqual(statistics, expected_0, 'The first statistics should be as expected: {0} vs {1}'.format(statistics, expected_0))
        time.sleep(5)
        asdmanager_client._results['get_disks'] = []
        AlbaCLI._run_results['asd-multistatistics'] = {'foo': {'success': True,
                                                               'result': {'Apply': {'n': 1, 'avg': 5, 'min': 5, 'max': 5},
                                                                          'MultiGet': {'n': 5, 'avg': 10, 'min': 5, 'max': 10},
                                                                          'MultiGet2': {'n': 5, 'avg': 15, 'min': 1, 'max': 5}}}}
        statistics = asd._statistics(AlbaASD._dynamics[0])
        expected_1['timestamp'] = base_time + 5
        self.assertDictEqual(statistics, expected_1, 'The second statistics should be as expected: {0} vs {1}'.format(statistics, expected_1))
