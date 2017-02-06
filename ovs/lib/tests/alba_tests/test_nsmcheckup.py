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
from ovs.dal.tests.alba_helpers import Helper as AlbaDalHelper
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

        VirtualAlbaBackend.clean()
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
        VirtualAlbaBackend.clean()

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
        VirtualAlbaBackend.clean()

    def tearDown(self):
        """
        Clean up test suite
        """
        self.persistent.clean()
        self.volatile.clean()
        VirtualAlbaBackend.clean()

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
        alba_structure = AlbaDalHelper.build_service_structure(
            {'alba_backends': [1]}
        )

        alba_backend = alba_structure['alba_backends'][1]
        storagerouter = structure['storagerouters'][1]
        System._machine_id = {storagerouter.ip: '1'}

        SSHClient._run_returns['ln -s /usr/lib/alba/albamgr_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend_1-abm/db'] = None
        SSHClient._run_returns['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend_1-nsm_0/db'] = None

        VirtualAlbaBackend.run_log = {}
        AlbaController.add_cluster(alba_backend.guid)

        # Validation of nsm_checkup
        with self.assertRaises(ValueError):
            AlbaController.nsm_checkup(min_nsms=0)  # Min_nsms should be at least 1

        # Validate single node NSM cluster
        self._validate_nsm([['1']])
        self.assertListEqual(VirtualAlbaBackend.run_log['backend_1-abm'], [['update_abm_client_config'],
                                                                           ['add_nsm_host', 'backend_1-nsm_0'],
                                                                           ['update_maintenance_config', 'set_lru_cache_eviction']])

        VirtualAlbaBackend.run_log['backend_1-abm'] = []
        AlbaController.nsm_checkup()

        # Running the NSM checkup should not change anything after an add_cluster
        self._validate_nsm([['1']])
        self.assertListEqual(VirtualAlbaBackend.run_log['backend_1-abm'], [])

        structure = Helper.build_service_structure(
            {'storagerouters': [2]},
            structure
        )
        System._machine_id = {storagerouter.ip: '1',
                              structure['storagerouters'][2].ip: '2'}
        VirtualAlbaBackend.run_log['backend_1-abm'] = []
        AlbaController.nsm_checkup()

        # There should still be one NSM, since the safety is still at 1
        self._validate_nsm([['1']])
        self.assertListEqual(VirtualAlbaBackend.run_log['backend_1-abm'], [])

        Configuration.set('/ovs/framework/plugins/alba/config|nsm.safety', 2)
        VirtualAlbaBackend.run_log['backend_1-abm'] = []
        AlbaController.nsm_checkup()

        # There should still be one NSM, since the ABM isn't extended yet
        self._validate_nsm([['1']])
        self.assertListEqual(VirtualAlbaBackend.run_log['backend_1-abm'], [])

        SSHClient._run_returns['arakoon --node 2 -config file://opt/OpenvStorage/config/framework.json?key=/ovs/arakoon/backend_1-abm/config -catchup-only'] = None
        SSHClient._run_returns['ln -s /usr/lib/alba/albamgr_plugin.cmxs /tmp/unittest/sr_2/disk_1/partition_1/arakoon/backend_1-abm/db'] = None
        VirtualAlbaBackend.run_log['backend_1-abm'] = []
        AlbaController.manual_alba_arakoon_checkup(alba_backend.guid)

        self.assertListEqual(VirtualAlbaBackend.run_log['backend_1-abm'], [['update_abm_client_config']])

        SSHClient._run_returns['arakoon --node 2 -config file://opt/OpenvStorage/config/framework.json?key=/ovs/arakoon/backend_1-nsm_0/config -catchup-only'] = None
        SSHClient._run_returns['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_2/disk_1/partition_1/arakoon/backend_1-nsm_0/db'] = None
        VirtualAlbaBackend.run_log['backend_1-abm'] = []
        AlbaController.nsm_checkup()

        # Now that the ABM was extended, the NSM should also be extended
        self._validate_nsm([['1', '2']])
        self.assertListEqual(VirtualAlbaBackend.run_log['backend_1-abm'], [['update_nsm_host', 'backend_1-nsm_0']])

        SSHClient._run_returns['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend_1-nsm_1/db'] = None
        SSHClient._run_returns['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_2/disk_1/partition_1/arakoon/backend_1-nsm_1/db'] = None
        SSHClient._run_returns['arakoon --node 1 -config file://opt/OpenvStorage/config/framework.json?key=/ovs/arakoon/backend_1-nsm_1/config -catchup-only'] = None
        SSHClient._run_returns['arakoon --node 2 -config file://opt/OpenvStorage/config/framework.json?key=/ovs/arakoon/backend_1-nsm_1/config -catchup-only'] = None
        VirtualAlbaBackend.run_log['backend_1-abm'] = []
        AlbaController.nsm_checkup(min_nsms=2)

        # A second NSM cluster (running on two nodes) should be added
        self._validate_nsm([['1', '2'],
                            ['1', '2']])
        self.assertListEqual(VirtualAlbaBackend.run_log['backend_1-abm'], [['add_nsm_host', 'backend_1-nsm_1']])

        VirtualAlbaBackend.data['backend_1-abm']['nsms'][0]['namespaces_count'] = 25

        VirtualAlbaBackend.run_log['backend_1-abm'] = []
        AlbaController.nsm_checkup()

        # Nothing should be happened, since there's still a non-overloaded NSM
        self._validate_nsm([['1', '2'],
                            ['1', '2']])
        self.assertListEqual(VirtualAlbaBackend.run_log['backend_1-abm'], [])

        VirtualAlbaBackend.data['backend_1-abm']['nsms'][1]['namespaces_count'] = 25

        SSHClient._run_returns['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend_1-nsm_2/db'] = None
        SSHClient._run_returns['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_2/disk_1/partition_1/arakoon/backend_1-nsm_2/db'] = None
        SSHClient._run_returns['arakoon --node 1 -config file://opt/OpenvStorage/config/framework.json?key=/ovs/arakoon/backend_1-nsm_2/config -catchup-only'] = None
        SSHClient._run_returns['arakoon --node 2 -config file://opt/OpenvStorage/config/framework.json?key=/ovs/arakoon/backend_1-nsm_2/config -catchup-only'] = None
        VirtualAlbaBackend.run_log['backend_1-abm'] = []
        AlbaController.nsm_checkup()

        # A third NSM cluster (running on two nodes) should be added
        self._validate_nsm([['1', '2'],
                            ['1', '2'],
                            ['1', '2']])
        self.assertListEqual(VirtualAlbaBackend.run_log['backend_1-abm'], [['add_nsm_host', 'backend_1-nsm_2']])

        VirtualAlbaBackend.run_log['backend_1-abm'] = []
        AlbaController.nsm_checkup()

        # Running the checkup should not change anything
        self._validate_nsm([['1', '2'],
                            ['1', '2'],
                            ['1', '2']])
        self.assertListEqual(VirtualAlbaBackend.run_log['backend_1-abm'], [])

        # Validate additional nsms logic
        with self.assertRaises(ValueError):
            AlbaController.nsm_checkup(additional_nsms={'amount': 1})  # No ALBA Backend specified
        with self.assertRaises(ValueError):
            AlbaController.nsm_checkup(alba_backend_guid=alba_backend.guid, min_nsms=2, additional_nsms={'amount': 1})  # min_nsms and additional_nsms are mutually exclusive
        with self.assertRaises(ValueError):
            AlbaController.nsm_checkup(alba_backend_guid=alba_backend.guid, additional_nsms={'names': []})  # amount should be specified in the 'additional_nsms' dict
        with self.assertRaises(ValueError):
            AlbaController.nsm_checkup(alba_backend_guid=alba_backend.guid, additional_nsms={'amount': 1, 'names': {}})  # names should be a dict in the 'additional_nsms' dict
        with self.assertRaises(ValueError):
            AlbaController.nsm_checkup(alba_backend_guid=alba_backend.guid, additional_nsms={'amount': 1, 'names': ['non-existing-cluster']})  # non-existing cluster names should raise

        # Add some additional internally managed NSMs
        current_nsms = [nsm_cluster.number for nsm_cluster in alba_backend.nsm_clusters]
        for x in range(len(current_nsms), len(current_nsms) + 2):
            SSHClient._run_returns['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend_1-nsm_{0}/db'.format(x)] = None
            SSHClient._run_returns['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_2/disk_1/partition_1/arakoon/backend_1-nsm_{0}/db'.format(x)] = None
            SSHClient._run_returns['arakoon --node 1 -config file://opt/OpenvStorage/config/framework.json?key=/ovs/arakoon/backend_1-nsm_{0}/config -catchup-only'.format(x)] = None
            SSHClient._run_returns['arakoon --node 2 -config file://opt/OpenvStorage/config/framework.json?key=/ovs/arakoon/backend_1-nsm_{0}/config -catchup-only'.format(x)] = None
        AlbaController.nsm_checkup(alba_backend_guid=alba_backend.guid, additional_nsms={'amount': 2})
        self._validate_nsm([['1', '2'],
                            ['1', '2'],
                            ['1', '2'],
                            ['1', '2'],
                            ['1', '2']])

        # Validate a maximum of 50 NSMs can be deployed
        current_nsms = [nsm_cluster.number for nsm_cluster in alba_backend.nsm_clusters]
        alba_structure = AlbaDalHelper.build_service_structure(
            structure={'alba_nsm_clusters': [(1, 50)]},  # (<abackend_id>, <amount_of_nsm_clusters>)
            previous_structure=alba_structure
        )
        with self.assertRaises(ValueError):
            AlbaController.nsm_checkup(alba_backend_guid=alba_backend.guid, additional_nsms={'amount': 1})  # Maximum of NSM clusters will now be exceeded

        # Basic externally managed NSM checkup validation
        for nsm_cluster in alba_structure['alba_nsm_clusters'][1][len(current_nsms):]:
            for nsm_service in nsm_cluster.nsm_services:
                nsm_service.delete()
                nsm_service.service.delete()
            nsm_cluster.delete()

        alba_backend.abm_cluster.abm_services[0].service.storagerouter = None
        alba_backend.abm_cluster.abm_services[0].service.save()
        alba_backend.abm_cluster.abm_services[0].service.invalidate_dynamics('is_internal')
        with self.assertRaises(ValueError):
            AlbaController.nsm_checkup(alba_backend_guid=alba_backend.guid, additional_nsms={'amount': 1})  # No unused externally managed clusters are available
        with self.assertRaises(ValueError):
            AlbaController.nsm_checkup(alba_backend_guid=alba_backend.guid, additional_nsms={'amount': 0, 'names': ['backend_1-nsm_0']})  # The provided cluster_name to claim has already been claimed

    def _validate_nsm(self, config):
        nsm_layout = {}
        self.assertEqual(len(VirtualAlbaBackend.data['backend_1-abm']['nsms']), len(config))
        for i in xrange(len(config)):
            expected = copy.deepcopy(VirtualAlbaBackend.data['backend_1-abm']['nsms'][i])
            expected['id'] = 'backend_1-nsm_{0}'.format(i)
            self.assertDictEqual(VirtualAlbaBackend.data['backend_1-abm']['nsms'][i], expected)
            nsm_layout['backend_1-nsm_{0}'.format(i)] = config[i]
        self.assertDictEqual(VirtualAlbaBackend._get_nsm_state('backend_1-abm'), nsm_layout)
