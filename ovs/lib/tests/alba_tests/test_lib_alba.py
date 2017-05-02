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
ALBA generic test module
"""
import unittest
from ovs.dal.hybrids.servicetype import ServiceType
from ovs.dal.tests.alba_helpers import AlbaDalHelper
from ovs.dal.tests.helpers import DalHelper
from ovs.extensions.db.arakoon.arakooninstaller import ArakoonInstaller
from ovs.extensions.generic.configuration import Configuration
from ovs.extensions.generic.sshclient import SSHClient, UnableToConnectException
from ovs.extensions.generic.tests.sshclient_mock import MockedSSHClient
from ovs.lib.alba import AlbaController
from ovs.log.log_handler import LogHandler


class AlbaGeneric(unittest.TestCase):
    """
    This test class will validate various ALBA generic scenarios
    """
    def setUp(self):
        """
        (Re)Sets the stores on every test
        """
        AlbaDalHelper.setup()

    def tearDown(self):
        """
        Clean up test suite
        """
        AlbaDalHelper.teardown()

    def test_alba_arakoon_checkup(self):
        """
        Validates whether the ALBA Arakoon checkup works (Manual and Scheduled)
        """
        ovs_structure = DalHelper.build_dal_structure(structure={'storagerouters': [1]})
        alba_structure = AlbaDalHelper.build_dal_structure(structure={'alba_backends': [1]})

        #############################
        # SCHEDULED_ARAKOON_CHECKUP #
        #############################
        # Create an ABM and NSM cluster for ALBA Backend 1 and do some basic validations
        sr_1 = ovs_structure['storagerouters'][1]
        ab_1 = alba_structure['alba_backends'][1]
        MockedSSHClient._run_returns[sr_1.ip] = {}
        MockedSSHClient._run_returns[sr_1.ip]['ln -s /usr/lib/alba/albamgr_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend_1-abm/db'] = None
        MockedSSHClient._run_returns[sr_1.ip]['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend_1-nsm_0/db'] = None
        AlbaController.add_cluster(ab_1.guid)

        abm_cluster_name = '{0}-abm'.format(ab_1.name)
        nsm_cluster_name = '{0}-nsm_0'.format(ab_1.name)
        arakoon_clusters = sorted(Configuration.list('/ovs/arakoon'))
        self.assertListEqual(list1=[abm_cluster_name, nsm_cluster_name], list2=arakoon_clusters)

        abm_metadata = ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=abm_cluster_name)
        nsm_metadata = ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=nsm_cluster_name)
        self.assertTrue(expr=abm_metadata['in_use'])
        self.assertTrue(expr=nsm_metadata['in_use'])

        # Run scheduled Arakoon checkup and validate amount of Arakoon clusters did not change
        AlbaController.scheduled_alba_arakoon_checkup()
        self.assertListEqual(list1=[abm_cluster_name, nsm_cluster_name], list2=arakoon_clusters)
        self.assertEqual(first=len(ab_1.abm_cluster.abm_services), second=1)
        self.assertEqual(first=len(ab_1.nsm_clusters), second=1)
        self.assertEqual(first=len(ab_1.nsm_clusters[0].nsm_services), second=1)

        # Create 2 additional StorageRouters
        srs = DalHelper.build_dal_structure(structure={'storagerouters': [2, 3]}, previous_structure=ovs_structure)['storagerouters']
        sr_2 = srs[2]
        sr_3 = srs[3]

        # Run scheduled checkup again and do some validations
        MockedSSHClient._run_returns[sr_2.ip] = {}
        MockedSSHClient._run_returns[sr_3.ip] = {}
        MockedSSHClient._run_returns[sr_2.ip]['ln -s /usr/lib/alba/albamgr_plugin.cmxs /tmp/unittest/sr_2/disk_1/partition_1/arakoon/backend_1-abm/db'] = None
        MockedSSHClient._run_returns[sr_3.ip]['ln -s /usr/lib/alba/albamgr_plugin.cmxs /tmp/unittest/sr_3/disk_1/partition_1/arakoon/backend_1-abm/db'] = None
        MockedSSHClient._run_returns[sr_2.ip]['arakoon --node {0} -config file://opt/OpenvStorage/config/framework.json?key=/ovs/arakoon/backend_1-abm/config -catchup-only'.format(sr_2.machine_id)] = None
        MockedSSHClient._run_returns[sr_3.ip]['arakoon --node {0} -config file://opt/OpenvStorage/config/framework.json?key=/ovs/arakoon/backend_1-abm/config -catchup-only'.format(sr_3.machine_id)] = None
        AlbaController.scheduled_alba_arakoon_checkup()
        self.assertListEqual(list1=[abm_cluster_name, nsm_cluster_name], list2=arakoon_clusters)
        self.assertEqual(first=len(ab_1.abm_cluster.abm_services), second=3)  # Gone up from 1 to 3
        self.assertEqual(first=len(ab_1.nsm_clusters), second=1)
        self.assertEqual(first=len(ab_1.nsm_clusters[0].nsm_services), second=1)  # Still 1 since NSM checkup hasn't ran yet

        # Make sure 1 StorageRouter is unreachable
        SSHClient._raise_exceptions[sr_3.ip] = {'users': ['ovs'],
                                                'exception': UnableToConnectException('No route to host')}
        AlbaController.scheduled_alba_arakoon_checkup()
        alba_logs = LogHandler._logs.get('lib_alba', [])
        self.assertIn(member='Storage Router with IP {0} is not reachable'.format(sr_3.ip),
                      container=alba_logs)

        ##########################
        # MANUAL_ARAKOON_CHECKUP #
        ##########################
        AlbaDalHelper.setup()  # Clear everything
        ovs_structure = DalHelper.build_dal_structure(structure={'storagerouters': [1]})
        alba_structure = AlbaDalHelper.build_dal_structure(structure={'alba_backends': [1]})
        sr_1 = ovs_structure['storagerouters'][1]
        ab_1 = alba_structure['alba_backends'][1]
        MockedSSHClient._run_returns[sr_1.ip] = {}
        MockedSSHClient._run_returns[sr_1.ip]['ln -s /usr/lib/alba/albamgr_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend_1-abm/db'] = None
        MockedSSHClient._run_returns[sr_1.ip]['ln -s /usr/lib/alba/nsm_host_plugin.cmxs /tmp/unittest/sr_1/disk_1/partition_1/arakoon/backend_1-nsm_0/db'] = None
        AlbaController.add_cluster(ab_1.guid)

        # Run manual Arakoon checkup and validate amount of Arakoon clusters did not change
        AlbaController.manual_alba_arakoon_checkup(alba_backend_guid=ab_1.guid, nsm_clusters=[], abm_cluster=None)
        self.assertListEqual(list1=[abm_cluster_name, nsm_cluster_name], list2=arakoon_clusters)
        self.assertEqual(first=len(ab_1.abm_cluster.abm_services), second=1)
        self.assertEqual(first=len(ab_1.nsm_clusters), second=1)
        self.assertEqual(first=len(ab_1.nsm_clusters[0].nsm_services), second=1)

        # Test some error paths
        with self.assertRaises(ValueError) as raise_info:
            AlbaController.manual_alba_arakoon_checkup(alba_backend_guid=ab_1.guid, nsm_clusters=['no_abm_cluster_passed'])
        self.assertEqual(first=raise_info.exception.message,
                         second='Both ABM cluster and NSM clusters must be provided')
        with self.assertRaises(ValueError) as raise_info:
            AlbaController.manual_alba_arakoon_checkup(alba_backend_guid=ab_1.guid, nsm_clusters=[], abm_cluster='no_nsm_clusters_passed')
        self.assertEqual(first=raise_info.exception.message,
                         second='Both ABM cluster and NSM clusters must be provided')
        with self.assertRaises(ValueError) as raise_info:
            AlbaController.manual_alba_arakoon_checkup(alba_backend_guid=ab_1.guid, nsm_clusters=[nsm_cluster_name], abm_cluster=abm_cluster_name)
        self.assertEqual(first=raise_info.exception.message,
                         second='Cluster {0} has already been claimed'.format(abm_cluster_name))
        with self.assertRaises(ValueError) as raise_info:
            AlbaController.manual_alba_arakoon_checkup(alba_backend_guid=ab_1.guid, nsm_clusters=['non-existing-nsm-cluster'], abm_cluster='non-existing-abm-cluster')
        self.assertEqual(first=raise_info.exception.message,
                         second='Could not find an Arakoon cluster with name: non-existing-abm-cluster')

        # Recreate ALBA Backend with Arakoon clusters
        AlbaDalHelper.setup()  # Clear everything
        ovs_structure = DalHelper.build_dal_structure(structure={'storagerouters': [1]})
        alba_structure = AlbaDalHelper.build_dal_structure(structure={'alba_backends': [1]})
        sr_1 = ovs_structure['storagerouters'][1]
        ab_1 = alba_structure['alba_backends'][1]

        # Create some Arakoon clusters to be claimed by the manual checkup
        for cluster_name, cluster_type in {'manual-abm-1': ServiceType.ARAKOON_CLUSTER_TYPES.ABM,
                                           'manual-abm-2': ServiceType.ARAKOON_CLUSTER_TYPES.ABM,
                                           'manual-nsm-1': ServiceType.ARAKOON_CLUSTER_TYPES.NSM,
                                           'manual-nsm-2': ServiceType.ARAKOON_CLUSTER_TYPES.NSM,
                                           'manual-nsm-3': ServiceType.ARAKOON_CLUSTER_TYPES.NSM}.iteritems():
            info = ArakoonInstaller.create_cluster(cluster_name=cluster_name,
                                                   cluster_type=cluster_type,
                                                   ip=sr_1.ip,
                                                   base_dir=DalHelper.CLUSTER_DIR.format(cluster_name),
                                                   internal=False)
            ArakoonInstaller.start_cluster(metadata=info['metadata'])
            ArakoonInstaller.unclaim_cluster(cluster_name=cluster_name)
        AlbaController.manual_alba_arakoon_checkup(alba_backend_guid=ab_1.guid, nsm_clusters=['manual-nsm-1', 'manual-nsm-3'], abm_cluster='manual-abm-2')

        # Validate the correct clusters have been claimed by the manual checkup
        unused_abms = ArakoonInstaller.get_unused_arakoon_clusters(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.ABM)
        unused_nsms = ArakoonInstaller.get_unused_arakoon_clusters(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM)
        self.assertEqual(first=len(unused_abms), second=1)
        self.assertEqual(first=len(unused_nsms), second=1)
        self.assertEqual(first=unused_abms[0]['cluster_name'], second='manual-abm-1')
        self.assertEqual(first=unused_nsms[0]['cluster_name'], second='manual-nsm-2')
