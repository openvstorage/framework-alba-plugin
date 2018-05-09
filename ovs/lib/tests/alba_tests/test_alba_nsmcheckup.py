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
from ovs.extensions.db.arakooninstaller import ArakoonInstaller
from ovs.extensions.generic.configuration import Configuration
from ovs_extensions.generic.tests.sshclient_mock import MockedSSHClient
from ovs_extensions.log.logger import Logger
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

    def _validate_nsm(self, config):
        nsm_layout = {}
        self.assertEqual(len(VirtualAlbaBackend.data['backend_1-abm']['nsms']), len(config))
        for i in xrange(len(config)):
            expected = copy.deepcopy(VirtualAlbaBackend.data['backend_1-abm']['nsms'][i])
            expected['id'] = 'backend_1-nsm_{0}'.format(i)
            self.assertDictEqual(VirtualAlbaBackend.data['backend_1-abm']['nsms'][i], expected)
            nsm_layout['backend_1-nsm_{0}'.format(i)] = config[i]
        self.assertDictEqual(VirtualAlbaBackend._get_nsm_state('backend_1-abm'), nsm_layout)

    def test_nsm_checkup_internal(self):
        """
        Validates whether the NSM checkup works for internally managed Arakoon clusters
        """
        Configuration.set('/ovs/framework/plugins/alba/config|nsm.safety', 1)
        Configuration.set('/ovs/framework/plugins/alba/config|nsm.maxload', 10)

        structure = DalHelper.build_dal_structure(structure={'storagerouters': [1]})
        alba_structure = AlbaDalHelper.build_dal_structure(structure={'alba_backends': [[1, 'LOCAL']]})

        alba_backend = alba_structure['alba_backends'][1]
        storagerouter_1 = structure['storagerouters'][1]

        MockedSSHClient._run_returns[storagerouter_1.ip] = {}
        MockedSSHClient._run_returns[storagerouter_1.ip]['ln -s /usr/lib/alba/albamgr_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend_1-abm/db'] = None
        MockedSSHClient._run_returns[storagerouter_1.ip]['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend_1-nsm_0/db'] = None

        VirtualAlbaBackend.run_log = {}
        AlbaController.add_cluster(alba_backend.guid)

        # Validation of nsm_checkup
        with self.assertRaises(ValueError):
            AlbaController.nsm_checkup(min_internal_nsms=0)  # Min_nsms should be at least 1

        # Validate single node NSM cluster
        self._validate_nsm([['1']])
        self.assertListEqual(VirtualAlbaBackend.run_log['backend_1-abm'], [['update_abm_client_config'],
                                                                           ['add_nsm_host', 'backend_1-nsm_0'],
                                                                           ['update_maintenance_config', '--eviction-type-random'],
                                                                           ['update_maintenance_config', 'enable-auto-cleanup-deleted-namespaces-days']])

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
        AlbaController.nsm_checkup(min_internal_nsms=2)

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

    def test_nsm_checkup_external(self):
        """
        Validates whether the NSM checkup works for externally managed Arakoon clusters
        """
        Configuration.set('/ovs/framework/plugins/alba/config|nsm.safety', 1)
        Configuration.set('/ovs/framework/plugins/alba/config|nsm.maxload', 10)

        structure = DalHelper.build_dal_structure(structure={'storagerouters': [1, 2, 3]})
        alba_structure = AlbaDalHelper.build_dal_structure(structure={'alba_backends': [[1, 'LOCAL']]})

        alba_backend = alba_structure['alba_backends'][1]
        storagerouter_1 = structure['storagerouters'][1]
        storagerouter_2 = structure['storagerouters'][2]

        # Validate some logic for externally managed arakoons during NSM checkup
        with self.assertRaises(ValueError) as raise_info:
            AlbaController.nsm_checkup(external_nsm_cluster_names=['test'])  # No ALBA Backend specified
        self.assertEqual(first=str(raise_info.exception), second='Additional NSMs can only be configured for a specific ALBA Backend')
        with self.assertRaises(ValueError) as raise_info:
            AlbaController.nsm_checkup(alba_backend_guid=alba_backend.guid, min_internal_nsms=2, external_nsm_cluster_names=['test'])
        self.assertEqual(first=str(raise_info.exception), second="'min_internal_nsms' and 'external_nsm_cluster_names' are mutually exclusive")
        with self.assertRaises(ValueError) as raise_info:
            # noinspection PyTypeChecker
            AlbaController.nsm_checkup(alba_backend_guid=alba_backend.guid, external_nsm_cluster_names={})  # NSM cluster names must be a list
        self.assertEqual(first=str(raise_info.exception), second="'external_nsm_cluster_names' must be of type 'list'")
        with self.assertRaises(ValueError) as raise_info:
            AlbaController.nsm_checkup(alba_backend_guid=alba_backend.guid, external_nsm_cluster_names=['non-existing-cluster'])  # non-existing cluster names should raise
        self.assertEqual(first=str(raise_info.exception), second="Arakoon cluster with name non-existing-cluster does not exist")

        # Create an external ABM and NSM Arakoon cluster
        external_abm_1 = 'backend_1-abm'
        external_nsm_1 = 'backend_1-nsm_0'
        external_nsm_2 = 'backend_1-nsm_1'
        for cluster_name, cluster_type in {external_abm_1: 'ABM', external_nsm_1: 'NSM', external_nsm_2: 'NSM'}.iteritems():
            arakoon_installer = ArakoonInstaller(cluster_name=cluster_name)
            arakoon_installer.create_cluster(cluster_type=cluster_type, ip=storagerouter_1.ip, base_dir='/tmp', internal=False)
            arakoon_installer.extend_cluster(new_ip=storagerouter_2.ip, base_dir='/tmp')
            arakoon_installer.start_cluster()
            arakoon_installer.unclaim_cluster()
            self.assertDictEqual(d1={'cluster_name': cluster_name,
                                     'cluster_type': cluster_type,
                                     'internal': False,
                                     'in_use': False},
                                 d2=arakoon_installer.get_arakoon_metadata_by_cluster_name(cluster_name=cluster_name))

        # Let the 'add_cluster` claim the externally managed clusters and model the services
        Logger._logs = {}
        AlbaController.add_cluster(alba_backend_guid=alba_backend.guid,
                                   abm_cluster=external_abm_1,
                                   nsm_clusters=[external_nsm_1])  # Only claim external_nsm_1
        for cluster_name, cluster_type in {external_abm_1: 'ABM', external_nsm_1: 'NSM', external_nsm_2: 'NSM'}.iteritems():
            arakoon_installer = ArakoonInstaller(cluster_name=cluster_name)
            self.assertDictEqual(d1={'cluster_name': cluster_name,
                                     'cluster_type': cluster_type,
                                     'internal': False,
                                     'in_use': False if cluster_name == external_nsm_2 else True},
                                 d2=arakoon_installer.get_arakoon_metadata_by_cluster_name(cluster_name=cluster_name))
        log_found = False
        for log_record in Logger._logs.get('lib', []):
            if 'NSM load OK' in log_record:
                log_found = True
                break
        self.assertTrue(expr=log_found)
        self.assertEqual(first=1, second=len(alba_backend.abm_cluster.abm_services))
        self.assertEqual(first=1, second=len(alba_backend.nsm_clusters))
        self.assertEqual(first=1, second=len(alba_backend.nsm_clusters[0].nsm_services))
        self.assertIsNone(obj=alba_backend.abm_cluster.abm_services[0].service.storagerouter)
        self.assertIsNone(obj=alba_backend.nsm_clusters[0].nsm_services[0].service.storagerouter)
        self.assertListEqual(VirtualAlbaBackend.run_log['backend_1-abm'], [['update_abm_client_config'],
                                                                           ['add_nsm_host', 'backend_1-nsm_0'],
                                                                           ['update_maintenance_config','--eviction-type-random'],
                                                                           ['update_maintenance_config','enable-auto-cleanup-deleted-namespaces-days']])

        # Add cluster already invokes a NSM checkup, so nothing should have changed
        VirtualAlbaBackend.run_log['backend_1-abm'] = []
        AlbaController.nsm_checkup()
        self.assertListEqual(list1=[], list2=VirtualAlbaBackend.run_log['backend_1-abm'])

        # Overload the only NSM and run NSM checkup. This should log a critical message, but change nothing
        VirtualAlbaBackend.data['backend_1-abm']['nsms'][0]['namespaces_count'] = 25
        Logger._logs = {}
        AlbaController.nsm_checkup()
        log_found = False
        for log_record in Logger._logs.get('lib', []):
            if 'All NSM clusters are overloaded' in log_record:
                log_found = True
                break
        self.assertTrue(expr=log_found)
        self.assertEqual(first=1, second=len(alba_backend.abm_cluster.abm_services))
        self.assertEqual(first=1, second=len(alba_backend.nsm_clusters))
        self.assertEqual(first=1, second=len(alba_backend.nsm_clusters[0].nsm_services))
        self.assertIsNone(obj=alba_backend.abm_cluster.abm_services[0].service.storagerouter)
        self.assertIsNone(obj=alba_backend.nsm_clusters[0].nsm_services[0].service.storagerouter)
        self.assertListEqual(list1=[], list2=VirtualAlbaBackend.run_log['backend_1-abm'])

        # Validate a maximum of 50 NSMs can be deployed
        current_nsms = [nsm_cluster.number for nsm_cluster in alba_backend.nsm_clusters]
        alba_structure = AlbaDalHelper.build_dal_structure(
            structure={'alba_nsm_clusters': [(1, 50)]},  # (<abackend_id>, <amount_of_nsm_clusters>)
            previous_structure=alba_structure
        )
        # Try to add 1 additional NSM
        with self.assertRaises(ValueError) as raise_info:
            AlbaController.nsm_checkup(alba_backend_guid=alba_backend.guid, external_nsm_cluster_names=[external_nsm_2])
        self.assertEqual(first=str(raise_info.exception), second='The maximum of 50 NSM Arakoon clusters will be exceeded. Amount of clusters that can be deployed for this ALBA Backend: 0')

        # Remove the unused NSM clusters again
        for nsm_cluster in alba_structure['alba_nsm_clusters'][1][len(current_nsms):]:
            for nsm_service in nsm_cluster.nsm_services:
                nsm_service.delete()
                nsm_service.service.delete()
            nsm_cluster.delete()

        # Try to add a previously claimed NSM cluster
        with self.assertRaises(ValueError) as raise_info:
            AlbaController.nsm_checkup(alba_backend_guid=alba_backend.guid, external_nsm_cluster_names=[external_nsm_1])  # The provided cluster_name to claim has already been claimed
        self.assertEqual(first=str(raise_info.exception), second='Some of the provided cluster_names have already been claimed before')

        # Add a 2nd NSM cluster
        AlbaController.nsm_checkup(alba_backend_guid=alba_backend.guid, external_nsm_cluster_names=[external_nsm_2])
        self.assertEqual(first=1, second=len(alba_backend.abm_cluster.abm_services))
        self.assertEqual(first=2, second=len(alba_backend.nsm_clusters))
        self.assertEqual(first=1, second=len(alba_backend.nsm_clusters[0].nsm_services))
        self.assertEqual(first=1, second=len(alba_backend.nsm_clusters[1].nsm_services))
        self.assertIsNone(obj=alba_backend.abm_cluster.abm_services[0].service.storagerouter)
        self.assertIsNone(obj=alba_backend.nsm_clusters[0].nsm_services[0].service.storagerouter)
        self.assertIsNone(obj=alba_backend.nsm_clusters[1].nsm_services[0].service.storagerouter)
        self.assertListEqual(list1=[['add_nsm_host', 'backend_1-nsm_1']], list2=VirtualAlbaBackend.run_log['backend_1-abm'])
        for cluster_name, cluster_type in {external_abm_1: 'ABM', external_nsm_1: 'NSM', external_nsm_2: 'NSM'}.iteritems():
            arakoon_installer = ArakoonInstaller(cluster_name=cluster_name)
            self.assertDictEqual(d1={'cluster_name': cluster_name,
                                     'cluster_type': cluster_type,
                                     'internal': False,
                                     'in_use': True},
                                 d2=arakoon_installer.get_arakoon_metadata_by_cluster_name(cluster_name=cluster_name))
