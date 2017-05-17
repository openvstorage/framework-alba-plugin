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
from ovs.dal.tests.alba_helpers import AlbaDalHelper
from ovs.dal.tests.helpers import DalHelper
from ovs.extensions.generic.configuration import Configuration
from ovs_extensions.generic.tests.sshclient_mock import MockedSSHClient
from ovs.extensions.plugins.tests.alba_mockups import VirtualAlbaBackend
from ovs.lib.alba import AlbaController


class NSMCheckup(unittest.TestCase):
    """
    This test class will validate the various scenarios of the ALBA NSM logic
    """
    def setUp(self):
        """
        (Re)Sets the stores on every test
        """
        AlbaDalHelper.setup()
        Configuration.set('/ovs/framework/logging|path', '/var/log/ovs')
        Configuration.set('/ovs/framework/logging|level', 'DEBUG')
        Configuration.set('/ovs/framework/logging|default_file', 'generic')
        Configuration.set('/ovs/framework/logging|default_name', 'logger')

    def tearDown(self):
        """
        Clean up test suite
        """
        AlbaDalHelper.teardown()

    def test_nsm_checkup(self):
        """
        Validates whether the NSM checkup works
        """
        Configuration.set('/ovs/framework/plugins/alba/config|nsm.safety', 1)
        Configuration.set('/ovs/framework/plugins/alba/config|nsm.maxload', 10)

        structure = DalHelper.build_dal_structure(structure={'storagerouters': [1]})
        alba_structure = AlbaDalHelper.build_dal_structure(structure={'alba_backends': [1]})

        alba_backend = alba_structure['alba_backends'][1]
        storagerouter_1 = structure['storagerouters'][1]

        MockedSSHClient._run_returns[storagerouter_1.ip] = {}
        MockedSSHClient._run_returns[storagerouter_1.ip]['ln -s /usr/lib/alba/albamgr_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend_1-abm/db'] = None
        MockedSSHClient._run_returns[storagerouter_1.ip]['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend_1-nsm_0/db'] = None

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

        structure = DalHelper.build_dal_structure(structure={'storagerouters': [2]}, previous_structure=structure)
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

        storagerouter_2 = structure['storagerouters'][2]
        MockedSSHClient._run_returns[storagerouter_2.ip] = {}
        MockedSSHClient._run_returns[storagerouter_2.ip]['arakoon --node 2 -config file://opt/OpenvStorage/config/framework.json?key=/ovs/arakoon/backend_1-abm/config -catchup-only'] = None
        MockedSSHClient._run_returns[storagerouter_2.ip]['ln -s /usr/lib/alba/albamgr_plugin.cmxs /tmp/unittest/sr_2/disk_1/partition_1/arakoon/backend_1-abm/db'] = None
        VirtualAlbaBackend.run_log['backend_1-abm'] = []
        AlbaController.manual_alba_arakoon_checkup(alba_backend.guid, nsm_clusters=[])

        self.assertListEqual(VirtualAlbaBackend.run_log['backend_1-abm'], [['update_abm_client_config']])

        MockedSSHClient._run_returns[storagerouter_2.ip]['arakoon --node 2 -config file://opt/OpenvStorage/config/framework.json?key=/ovs/arakoon/backend_1-nsm_0/config -catchup-only'] = None
        MockedSSHClient._run_returns[storagerouter_2.ip]['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_2/disk_1/partition_1/arakoon/backend_1-nsm_0/db'] = None
        VirtualAlbaBackend.run_log['backend_1-abm'] = []
        AlbaController.nsm_checkup()

        # Now that the ABM was extended, the NSM should also be extended
        self._validate_nsm([['1', '2']])
        self.assertListEqual(VirtualAlbaBackend.run_log['backend_1-abm'], [['update_nsm_host', 'backend_1-nsm_0']])

        MockedSSHClient._run_returns[storagerouter_1.ip]['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend_1-nsm_1/db'] = None
        MockedSSHClient._run_returns[storagerouter_2.ip]['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend_1-nsm_1/db'] = None
        MockedSSHClient._run_returns[storagerouter_1.ip]['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_2/disk_1/partition_1/arakoon/backend_1-nsm_1/db'] = None
        MockedSSHClient._run_returns[storagerouter_2.ip]['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_2/disk_1/partition_1/arakoon/backend_1-nsm_1/db'] = None
        MockedSSHClient._run_returns[storagerouter_1.ip]['arakoon --node 1 -config file://opt/OpenvStorage/config/framework.json?key=/ovs/arakoon/backend_1-nsm_1/config -catchup-only'] = None
        MockedSSHClient._run_returns[storagerouter_2.ip]['arakoon --node 2 -config file://opt/OpenvStorage/config/framework.json?key=/ovs/arakoon/backend_1-nsm_1/config -catchup-only'] = None
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

        MockedSSHClient._run_returns[storagerouter_1.ip]['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend_1-nsm_2/db'] = None
        MockedSSHClient._run_returns[storagerouter_2.ip]['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend_1-nsm_2/db'] = None
        MockedSSHClient._run_returns[storagerouter_1.ip]['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_2/disk_1/partition_1/arakoon/backend_1-nsm_2/db'] = None
        MockedSSHClient._run_returns[storagerouter_2.ip]['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_2/disk_1/partition_1/arakoon/backend_1-nsm_2/db'] = None
        MockedSSHClient._run_returns[storagerouter_1.ip]['arakoon --node 1 -config file://opt/OpenvStorage/config/framework.json?key=/ovs/arakoon/backend_1-nsm_2/config -catchup-only'] = None
        MockedSSHClient._run_returns[storagerouter_2.ip]['arakoon --node 2 -config file://opt/OpenvStorage/config/framework.json?key=/ovs/arakoon/backend_1-nsm_2/config -catchup-only'] = None
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
            MockedSSHClient._run_returns[storagerouter_1.ip]['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend_1-nsm_{0}/db'.format(x)] = None
            MockedSSHClient._run_returns[storagerouter_2.ip]['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend_1-nsm_{0}/db'.format(x)] = None
            MockedSSHClient._run_returns[storagerouter_1.ip]['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_2/disk_1/partition_1/arakoon/backend_1-nsm_{0}/db'.format(x)] = None
            MockedSSHClient._run_returns[storagerouter_2.ip]['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_2/disk_1/partition_1/arakoon/backend_1-nsm_{0}/db'.format(x)] = None
            MockedSSHClient._run_returns[storagerouter_1.ip]['arakoon --node 1 -config file://opt/OpenvStorage/config/framework.json?key=/ovs/arakoon/backend_1-nsm_{0}/config -catchup-only'.format(x)] = None
            MockedSSHClient._run_returns[storagerouter_2.ip]['arakoon --node 2 -config file://opt/OpenvStorage/config/framework.json?key=/ovs/arakoon/backend_1-nsm_{0}/config -catchup-only'.format(x)] = None
        AlbaController.nsm_checkup(alba_backend_guid=alba_backend.guid, additional_nsms={'amount': 2})
        self._validate_nsm([['1', '2'],
                            ['1', '2'],
                            ['1', '2'],
                            ['1', '2'],
                            ['1', '2']])

        # Validate a maximum of 50 NSMs can be deployed
        current_nsms = [nsm_cluster.number for nsm_cluster in alba_backend.nsm_clusters]
        alba_structure = AlbaDalHelper.build_dal_structure(
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
