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
NSMCheckup test module
"""
import copy
import unittest
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.backend import Backend
from ovs.dal.hybrids.backendtype import BackendType
from ovs.dal.hybrids.servicetype import ServiceType
from ovs.extensions.generic.configuration import Configuration
from ovs.extensions.generic.sshclient import SSHClient
from ovs.extensions.generic.system import System
from ovs.extensions.plugins.tests.alba_mockups import VirtualAlbaBackend
from ovs.extensions.storage.persistentfactory import PersistentFactory
from ovs.extensions.storage.volatilefactory import VolatileFactory
from ovs.lib.alba import AlbaController
from ovs.lib.tests.helpers import Helper


class NSMCheckup(unittest.TestCase):
    """
    This test class will validate the various scenarios of the MDSService logic
    """

    @classmethod
    def setUpClass(cls):
        """
        Sets up the unittest, mocking a certain set of 3rd party libraries and extensions.
        This makes sure the unittests can be executed without those libraries installed
        """
        cls.persistent = PersistentFactory.get_client()
        cls.persistent.clean()

        cls.volatile = VolatileFactory.get_client()
        cls.volatile.clean()

        Configuration.set('/ovs/framework/logging|path', '/var/log/ovs')
        Configuration.set('/ovs/framework/logging|level', 'DEBUG')
        Configuration.set('/ovs/framework/logging|default_file', 'generic')
        Configuration.set('/ovs/framework/logging|default_name', 'logger')

    @classmethod
    def tearDownClass(cls):
        """
        Tear down changes made during setUpClass
        """
        Configuration._unittest_data = {}

        cls.persistent = PersistentFactory.get_client()
        cls.persistent.clean()

        cls.volatile = VolatileFactory.get_client()
        cls.volatile.clean()

    def setUp(self):
        """
        (Re)Sets the stores on every test
        """
        self.persistent.clean()
        self.volatile.clean()
        self.maxDiff = None

    def tearDown(self):
        """
        Clean up test suite
        """
        self.persistent.clean()
        self.volatile.clean()

    def test_nsm_checkup(self):
        """
        Validates whether the NSM checkup works
        """
        Configuration.set('/ovs/framework/plugins/alba/config|nsm.safety', 1)
        Configuration.set('/ovs/framework/plugins/alba/config|nsm.maxload', 10)
        Configuration.set('/ovs/framework/hosts/1/ports|arakoon', [10000, 10100])
        Configuration.set('/ovs/framework/hosts/2/ports|arakoon', [10000, 10100])

        structure = Helper.build_service_structure(
            {'storagerouters': [1]}
        )

        for service_type_info in [ServiceType.SERVICE_TYPES.NS_MGR, ServiceType.SERVICE_TYPES.ALBA_MGR]:
            service_type = ServiceType()
            service_type.name = service_type_info
            service_type.save()
        backend_type = BackendType()
        backend_type.code = 'alba'
        backend_type.name = 'ALBA'
        backend_type.save()
        backend = Backend()
        backend.name = 'backend'
        backend.backend_type = backend_type
        backend.save()
        alba_backend = AlbaBackend()
        alba_backend.backend = backend
        alba_backend.scaling = 'LOCAL'
        alba_backend.save()

        storagerouter = structure['storagerouters'][1]
        System._machine_id = {storagerouter.ip: '1'}

        SSHClient._run_returns['ln -s /usr/lib/alba/albamgr_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend-abm/db'] = None
        SSHClient._run_returns['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend-nsm_0/db'] = None

        VirtualAlbaBackend.run_log = {}
        AlbaController.add_cluster(alba_backend.guid)

        # Validate single single node NSM cluster
        self._validate_nsm([['1']])
        self.assertListEqual(VirtualAlbaBackend.run_log['backend-abm'], [['update_abm_client_config'],
                                                                         ['add_nsm_host', 'backend-nsm_0'],
                                                                         ['update_maintenance_config', 'set_lru_cache_eviction']])

        VirtualAlbaBackend.run_log['backend-abm'] = []
        AlbaController.nsm_checkup()

        # Running the NSM checkup should not change anything after an add_cluster
        self._validate_nsm([['1']])
        self.assertListEqual(VirtualAlbaBackend.run_log['backend-abm'], [])

        structure = Helper.build_service_structure(
            {'storagerouters': [2]},
            structure
        )
        System._machine_id = {storagerouter.ip: '1',
                              structure['storagerouters'][2].ip: '2'}
        VirtualAlbaBackend.run_log['backend-abm'] = []
        AlbaController.nsm_checkup()

        # There should still be one NSM, since the safety is still at 1
        self._validate_nsm([['1']])
        self.assertListEqual(VirtualAlbaBackend.run_log['backend-abm'], [])

        Configuration.set('/ovs/framework/plugins/alba/config|nsm.safety', 2)
        VirtualAlbaBackend.run_log['backend-abm'] = []
        AlbaController.nsm_checkup()

        # There should still be one NSM, since the ABM isn't extended yet
        self._validate_nsm([['1']])
        self.assertListEqual(VirtualAlbaBackend.run_log['backend-abm'], [])

        SSHClient._run_returns['arakoon --node 2 -config file://opt/OpenvStorage/config/framework.json?key=/ovs/arakoon/backend-abm/config -catchup-only'] = None
        SSHClient._run_returns['ln -s /usr/lib/alba/albamgr_plugin.cmxs /tmp/unittest/sr_2/disk_1/partition_1/arakoon/backend-abm/db'] = None
        VirtualAlbaBackend.run_log['backend-abm'] = []
        AlbaController.manual_alba_arakoon_checkup(alba_backend.guid)

        self.assertListEqual(VirtualAlbaBackend.run_log['backend-abm'], [['update_abm_client_config']])

        SSHClient._run_returns['arakoon --node 2 -config file://opt/OpenvStorage/config/framework.json?key=/ovs/arakoon/backend-nsm_0/config -catchup-only'] = None
        SSHClient._run_returns['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_2/disk_1/partition_1/arakoon/backend-nsm_0/db'] = None
        VirtualAlbaBackend.run_log['backend-abm'] = []
        AlbaController.nsm_checkup()

        # Now that the ABM was extended, the NSM should also be extended
        self._validate_nsm([['1', '2']])
        self.assertListEqual(VirtualAlbaBackend.run_log['backend-abm'], [['update_nsm_host', 'backend-nsm_0']])

        SSHClient._run_returns['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend-nsm_1/db'] = None
        SSHClient._run_returns['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_2/disk_1/partition_1/arakoon/backend-nsm_1/db'] = None
        VirtualAlbaBackend.run_log['backend-abm'] = []
        AlbaController.nsm_checkup(min_nsms=2)

        # A second NSM cluster (running on two nodes) should be added
        self._validate_nsm([['1', '2'],
                            ['1', '2']])
        self.assertListEqual(VirtualAlbaBackend.run_log['backend-abm'], [['add_nsm_host', 'backend-nsm_1']])

        VirtualAlbaBackend.data['backend-abm']['nsms'][0]['namespaces_count'] = 25

        VirtualAlbaBackend.run_log['backend-abm'] = []
        AlbaController.nsm_checkup()

        # Nothing should be happened, since there's still a non-overloaded NSM
        self._validate_nsm([['1', '2'],
                            ['1', '2']])
        self.assertListEqual(VirtualAlbaBackend.run_log['backend-abm'], [])

        VirtualAlbaBackend.data['backend-abm']['nsms'][1]['namespaces_count'] = 25

        SSHClient._run_returns['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend-nsm_2/db'] = None
        SSHClient._run_returns['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_2/disk_1/partition_1/arakoon/backend-nsm_2/db'] = None
        VirtualAlbaBackend.run_log['backend-abm'] = []
        AlbaController.nsm_checkup()

        # A third NSM cluster (running on two nodes) should be added
        self._validate_nsm([['1', '2'],
                            ['1', '2'],
                            ['1', '2']])
        self.assertListEqual(VirtualAlbaBackend.run_log['backend-abm'], [['add_nsm_host', 'backend-nsm_2']])

        VirtualAlbaBackend.run_log['backend-abm'] = []
        AlbaController.nsm_checkup()

        # Running the checkup should not change anything
        self._validate_nsm([['1', '2'],
                            ['1', '2'],
                            ['1', '2']])
        self.assertListEqual(VirtualAlbaBackend.run_log['backend-abm'], [])

    def _validate_nsm(self, config):
        nsm_layout = {}
        self.assertEqual(len(VirtualAlbaBackend.data['backend-abm']['nsms']), len(config))
        for i in xrange(len(config)):
            expected = copy.deepcopy(VirtualAlbaBackend.data['backend-abm']['nsms'][i])
            expected['id'] = 'backend-nsm_{0}'.format(i)
            self.assertDictEqual(VirtualAlbaBackend.data['backend-abm']['nsms'][i], expected)
            nsm_layout['backend-nsm_{0}'.format(i)] = config[i]
        self.assertDictEqual(VirtualAlbaBackend._get_nsm_state('backend-abm'), nsm_layout)
