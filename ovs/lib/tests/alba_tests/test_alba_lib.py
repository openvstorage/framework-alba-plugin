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
from ovs.extensions.db.arakooninstaller import ArakoonInstaller
from ovs.extensions.generic.configuration import Configuration
from ovs.extensions.generic.sshclient import SSHClient, UnableToConnectException
from ovs_extensions.generic.tests.sshclient_mock import MockedSSHClient
from ovs_extensions.log.logger import Logger
from ovs.extensions.plugins.tests.alba_mockups import ManagerClientMockup, VirtualAlbaBackend
from ovs.lib.alba import AlbaController


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
        alba_structure = AlbaDalHelper.build_dal_structure(structure={'alba_backends': [[1, 'LOCAL']]})

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
        alba_logs = Logger._logs.get('lib', [])
        self.assertIn(member='Storage Router with IP {0} is not reachable'.format(sr_3.ip),
                      container=alba_logs)

        ##########################
        # MANUAL_ARAKOON_CHECKUP #
        ##########################
        AlbaDalHelper.setup()  # Clear everything
        ovs_structure = DalHelper.build_dal_structure(structure={'storagerouters': [1]})
        alba_structure = AlbaDalHelper.build_dal_structure(structure={'alba_backends': [[1, 'LOCAL']]})
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
        alba_structure = AlbaDalHelper.build_dal_structure(structure={'alba_backends': [[1, 'LOCAL']]})
        sr_1 = ovs_structure['storagerouters'][1]
        ab_1 = alba_structure['alba_backends'][1]

        # Create some Arakoon clusters to be claimed by the manual checkup
        for cluster_name, cluster_type in {'manual-abm-1': ServiceType.ARAKOON_CLUSTER_TYPES.ABM,
                                           'manual-abm-2': ServiceType.ARAKOON_CLUSTER_TYPES.ABM,
                                           'manual-nsm-1': ServiceType.ARAKOON_CLUSTER_TYPES.NSM,
                                           'manual-nsm-2': ServiceType.ARAKOON_CLUSTER_TYPES.NSM,
                                           'manual-nsm-3': ServiceType.ARAKOON_CLUSTER_TYPES.NSM}.iteritems():
            arakoon_installer = ArakoonInstaller(cluster_name=cluster_name)
            arakoon_installer.create_cluster(cluster_type=cluster_type,
                                             ip=sr_1.ip,
                                             base_dir=DalHelper.CLUSTER_DIR.format(cluster_name),
                                             internal=False)
            arakoon_installer.start_cluster()
            arakoon_installer.unclaim_cluster()
        AlbaController.manual_alba_arakoon_checkup(alba_backend_guid=ab_1.guid, nsm_clusters=['manual-nsm-1', 'manual-nsm-3'], abm_cluster='manual-abm-2')

        # Validate the correct clusters have been claimed by the manual checkup
        unused_abms = ArakoonInstaller.get_unused_arakoon_clusters(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.ABM)
        unused_nsms = ArakoonInstaller.get_unused_arakoon_clusters(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM)
        self.assertEqual(first=len(unused_abms), second=1)
        self.assertEqual(first=len(unused_nsms), second=1)
        self.assertEqual(first=unused_abms[0]['cluster_name'], second='manual-abm-1')
        self.assertEqual(first=unused_nsms[0]['cluster_name'], second='manual-nsm-2')

    def test_maintenance_agents_for_local_backends_w_layout(self):
        """
        Validates the checkup maintenance agents for LOCAL ALBA Backends with a specific layout specified
        Additionally test whether at least 1 maintenance agent gets deployed even though none of the ALBA Nodes is linked to the ALBA Backend
        """
        alba_structure = AlbaDalHelper.build_dal_structure(structure={'alba_nodes': [1, 2, 3, 4],
                                                                      'alba_backends': [[1, 'LOCAL']],
                                                                      'alba_abm_clusters': [1]})
        alba_backend = alba_structure['alba_backends'][1]
        config_key = AlbaController.AGENTS_LAYOUT_CONFIG_KEY.format(alba_backend.guid)
        unknown_node_name = 'non-existing-node'

        # Mock some return values for some of the calls performed by `checkup_maintenance_agents`
        for alba_node in alba_structure['alba_nodes'].itervalues():
            ManagerClientMockup.test_results[alba_node].update({'get_stack': {},
                                                                'get_service_status': {'status': [None, 'active']},
                                                                'add_maintenance_service': '',
                                                                'remove_maintenance_service': ''})

        ###############################
        # Verify incorrect layout value
        log_entry = 'Layout is not a list and will be ignored'
        Configuration.set(key=config_key, value=unknown_node_name)  # Value should be a list

        # Checkup maintenance agents will not find any suitable ALBA Nodes to deploy a maintenance agent on, because no ALBA Nodes are linked to the ALBA Backend yet,
        # therefore it'll deploy a maintenance on a random ALBA Node
        AlbaController.checkup_maintenance_agents()
        self.assertIn(member=log_entry, container=Logger._logs['lib'].keys())
        self.assertEqual(first='WARNING', second=Logger._logs['lib'][log_entry])

        # Example of ManagerClientMockup.maintenance_agents
        # {<AlbaNode (guid: c015cf06-8bd0-46c5-811d-41ac6f521a63, at: 0x7f77cb0af390)>: {'alba-maintenance_backend_1-J6PMBcEk1Ej42udp': ['node_1']}}
        self.assertEqual(first=1, second=len(ManagerClientMockup.maintenance_agents.keys()))  # Only 1 ALBA Node should have a maintenance agent running
        self.assertEqual(first=1, second=len(ManagerClientMockup.maintenance_agents.values()))  # Only 1 maintenance agent should have been deployed on that 1 ALBA Node
        alba_node_w_agent_1 = ManagerClientMockup.maintenance_agents.keys()[0]
        self.assertEqual(first=[alba_node_w_agent_1.node_id],
                         second=ManagerClientMockup.maintenance_agents[alba_node_w_agent_1].values()[0])  # Read preference must be the Node ID of the Node on which the maintenance was deployed

        # 3 out of 4 ALBA Nodes do not have a maintenance agent yet
        alba_nodes_wo_agent = [an for an in alba_structure['alba_nodes'].itervalues() if an != alba_node_w_agent_1]
        self.assertEqual(first=3, second=len(alba_nodes_wo_agent))

        # Link an ALBA Node without agent to the ALBA Backend, forcing the previously deployed service to be removed and a new 1 to be created on this ALBA Node
        alba_node = alba_nodes_wo_agent[0]
        VirtualAlbaBackend.data['127.0.0.1:35001'] = alba_backend.guid
        ManagerClientMockup.test_results[alba_node]['get_stack'] = {
            alba_node.node_id: {
                'osds': {
                    'osd_id_1': {
                        'ips': ['127.0.0.1'],
                        'port': 35001
                    }
                }
            }
        }
        alba_node.invalidate_dynamics('stack')
        AlbaController.checkup_maintenance_agents()
        self.assertEqual(first=1, second=len(ManagerClientMockup.maintenance_agents.keys()))  # Only 1 ALBA Node should have a maintenance agent running
        self.assertEqual(first=1, second=len(ManagerClientMockup.maintenance_agents.values()))  # Only 1 maintenance agent should have been deployed on that 1 ALBA Node
        self.assertNotEqual(first=alba_node_w_agent_1, second=alba_node)  # The maintenance agent should have moved to the node linked to the ALBA Backend
        self.assertEqual(first=[alba_node.node_id], second=ManagerClientMockup.maintenance_agents[alba_node].values()[0])  # Read preference must be the Node ID of the Node on which the maintenance was moved to

        # Re-scheduling a checkup should not change anything at this point
        AlbaController.checkup_maintenance_agents()
        self.assertEqual(first=1, second=len(ManagerClientMockup.maintenance_agents.keys()))  # Only 1 ALBA Node should have a maintenance agent running
        self.assertEqual(first=1, second=len(ManagerClientMockup.maintenance_agents.values()))  # Only 1 maintenance agent should have been deployed on that 1 ALBA Node
        alba_node_w_agent_2 = ManagerClientMockup.maintenance_agents.keys()[0]
        self.assertEqual(first=alba_node, second=alba_node_w_agent_2)  # The maintenance agent should not have moved

        # Set 2 out of 4 ALBA Nodes in the layout key
        alba_nodes_wo_agent = [an for an in alba_structure['alba_nodes'].itervalues() if an != alba_node_w_agent_2]
        self.assertEqual(first=3, second=len(alba_nodes_wo_agent))
        node_1 = alba_nodes_wo_agent[0]
        node_2 = alba_nodes_wo_agent[1]
        Configuration.set(key=config_key, value=[node_1.node_id, node_2.node_id])
        AlbaController.checkup_maintenance_agents()
        self.assertIn(member=node_1, container=ManagerClientMockup.maintenance_agents)  # Specified in the layout
        self.assertIn(member=node_2, container=ManagerClientMockup.maintenance_agents)  # Specified in the layout
        self.assertEqual(first=2, second=len(ManagerClientMockup.maintenance_agents))  # Only the 2 specified ALBA Nodes should be running a maintenance agent
        self.assertEqual(first=1, second=len(ManagerClientMockup.maintenance_agents[node_1]))  # 1 Maintenance agent for this ALBA Node
        self.assertEqual(first=1, second=len(ManagerClientMockup.maintenance_agents[node_2]))  # 1 Maintenance agent for this ALBA Node
        self.assertEqual(first=[node_1.node_id], second=ManagerClientMockup.maintenance_agents[node_1].values()[0])  # Validate the read preference
        self.assertEqual(first=[node_2.node_id], second=ManagerClientMockup.maintenance_agents[node_2].values()[0])  # Validate the read preference

        #########################################
        # Verify all ALBA Nodes unknown in layout
        Logger._logs['lib'] = {}
        log_entry = 'Layout does not contain any known/reachable nodes and will be ignored'
        Configuration.set(key=config_key, value=[unknown_node_name])  # Only unknown Nodes in layout
        AlbaController.checkup_maintenance_agents()
        self.assertIn(member=log_entry, container=Logger._logs['lib'].keys())
        self.assertEqual(first='WARNING', second=Logger._logs['lib'][log_entry])
        self.assertIn(member=alba_node, container=ManagerClientMockup.maintenance_agents)  # The ALBA Node linked to the ALBA Backend should again have the maintenance agent
        self.assertEqual(first=1, second=len(ManagerClientMockup.maintenance_agents[alba_node]))  # Only 1 maintenance agent should have been deployed
        self.assertEqual(first=[alba_node.node_id],
                         second=ManagerClientMockup.maintenance_agents[alba_node].values()[0])  # Read preference must be the Node ID of the Node on which the maintenance was deployed

        # 3 out of 4 ALBA Nodes do not have a maintenance agent yet
        alba_nodes_wo_agent = [an for an in alba_structure['alba_nodes'].itervalues() if an != alba_node_w_agent_1]
        self.assertEqual(first=3, second=len(alba_nodes_wo_agent))

        #############################################
        # Verify at least 1 known ALBA Node in layout
        Logger._logs['lib'] = {}
        node_3 = alba_structure['alba_nodes'][3]
        log_entry = 'Layout contains unknown/unreachable node {0}'.format(unknown_node_name)
        Configuration.set(key=config_key, value=[unknown_node_name, node_3.node_id])  # 1 known ALBA Node in layout
        AlbaController.checkup_maintenance_agents()
        self.assertIn(member=log_entry, container=Logger._logs['lib'].keys())
        self.assertEqual(first='WARNING', second=Logger._logs['lib'][log_entry])
        self.assertIn(member=node_3, container=ManagerClientMockup.maintenance_agents)  # The ALBA Node specified in the layout should have the maintenance agent
        self.assertEqual(first=1, second=len(ManagerClientMockup.maintenance_agents[node_3]))  # Only 1 maintenance agent should have been deployed
        self.assertEqual(first=[node_3.node_id],
                         second=ManagerClientMockup.maintenance_agents[node_3].values()[0])  # Read preference must be the Node ID of the Node on which the maintenance was deployed

        # 3 out of 4 ALBA Nodes do not have a maintenance agent yet
        alba_nodes_wo_agent = [an for an in alba_structure['alba_nodes'].itervalues() if an != node_3]
        self.assertEqual(first=3, second=len(alba_nodes_wo_agent))

    def test_maintenance_agents_for_local_backends_wo_layout(self):
        """
        Validates the checkup maintenance agents for LOCAL ALBA Backends without a specific layout specified
        Additionally test:
            * Checkup maintenance agents for a specific ALBA Backend
            * Downscale the required services
            * Upscale the required services
        """
        alba_structure = AlbaDalHelper.build_dal_structure(structure={'alba_nodes': [1, 2, 3, 4],
                                                                      'alba_backends': [[1, 'LOCAL']],
                                                                      'alba_abm_clusters': [1]})

        # Simulate every ALBA Node has 1 OSD for `alba_backend_1`
        local_ip = '127.0.0.1'
        alba_backend_1 = alba_structure['alba_backends'][1]
        for index, alba_node in enumerate(alba_structure['alba_nodes'].itervalues()):
            port = 35000 + index
            ManagerClientMockup.test_results[alba_node].update({'get_service_status': {'status': [None, 'active']},
                                                                'add_maintenance_service': '',
                                                                'remove_maintenance_service': '',
                                                                'get_stack': {alba_node.node_id: {'osds': {'osd_id_{0}'.format(index): {'ips': [local_ip],
                                                                                                                                           'port': port}}}}})
            VirtualAlbaBackend.data['{0}:{1}'.format(local_ip, port)] = alba_backend_1.guid

        # Since all ALBA Nodes (4) are suitable for a maintenance agent, we only deploy a default amount of 3
        AlbaController.checkup_maintenance_agents()
        # Example of ManagerClientMockup.maintenance_agents
        # {
        #     <AlbaNode (guid: d43df79f-9c47-4059-bd84-0f3ef81733c2, at: 0x7f80028e4750)>: {'alba-maintenance_backend_1-RWvL8aCzwIBk6FaZ': ['node_3']},
        #     <AlbaNode (guid: 5dbf972d-2619-48d1-adcd-86ec5b6342f7, at: 0x7f80027ee2d0)>: {'alba-maintenance_backend_1-OgvznajMoRagKCVb': ['node_2']},
        #     <AlbaNode (guid: 79a762f7-3019-4b86-80d6-a5560c52b208, at: 0x7f80027ee0d0)>: {'alba-maintenance_backend_1-ZV9v2vtRfvaYBhhw': ['node_4']}
        # }
        self.assertEqual(first=3, second=len(ManagerClientMockup.maintenance_agents))  # 3 out of 4 ALBA Nodes should have a maintenance agent
        for alba_node, maintenance_info in ManagerClientMockup.maintenance_agents.iteritems():
            self.assertEqual(first=1, second=len(maintenance_info))
            self.assertEqual(first=[alba_node.node_id], second=ManagerClientMockup.maintenance_agents[alba_node].values()[0])

        # Downscale the required amount of services from 3 to 2
        config_key = AlbaController.NR_OF_AGENTS_CONFIG_KEY.format(alba_backend_1.guid)
        Configuration.set(key=config_key, value=2)
        nodes_w_agents = ManagerClientMockup.maintenance_agents.keys()
        AlbaController.checkup_maintenance_agents()
        self.assertEqual(first=2, second=len(ManagerClientMockup.maintenance_agents))  # 2 out of 4 ALBA Nodes should have a maintenance agent now
        for alba_node, maintenance_info in ManagerClientMockup.maintenance_agents.iteritems():
            self.assertEqual(first=1, second=len(maintenance_info))
            self.assertEqual(first=[alba_node.node_id], second=ManagerClientMockup.maintenance_agents[alba_node].values()[0])
        for alba_node in ManagerClientMockup.maintenance_agents:
            self.assertIn(member=alba_node, container=nodes_w_agents)  # 1 removed, rest should still be part of previously used ALBA Nodes

        # Upscale the required amount of services from 2 to 3 again
        Configuration.set(key=config_key, value=3)
        AlbaController.checkup_maintenance_agents()
        self.assertEqual(first=3, second=len(ManagerClientMockup.maintenance_agents))  # 3 out of 4 ALBA Nodes should again have a maintenance agent
        for alba_node, maintenance_info in ManagerClientMockup.maintenance_agents.iteritems():
            self.assertEqual(first=1, second=len(maintenance_info))
            self.assertEqual(first=[alba_node.node_id], second=ManagerClientMockup.maintenance_agents[alba_node].values()[0])

        # Create an additional ALBA Backend and verify that it is not processed when asking to checkup the previously created ALBA Backend
        alba_structure = AlbaDalHelper.build_dal_structure(structure={'alba_backends': [[2, 'LOCAL']],
                                                                      'alba_abm_clusters': [2]},
                                                           previous_structure=alba_structure)
        alba_backend_2 = alba_structure['alba_backends'][2]
        AlbaController.checkup_maintenance_agents(alba_backend_guid=alba_backend_1.guid)  # Run checkup for previously created ALBA Backend, nothing should change
        self.assertEqual(first=3, second=len(ManagerClientMockup.maintenance_agents))  # 3 out of 4 ALBA Nodes should again have a maintenance agent
        for alba_node, maintenance_info in ManagerClientMockup.maintenance_agents.iteritems():
            self.assertEqual(first=1, second=len(maintenance_info))
            self.assertEqual(first=[alba_node.node_id], second=ManagerClientMockup.maintenance_agents[alba_node].values()[0])

        # Execute a general checkup maintenance agents and verify newly created ALBA Backend has 1 service (because not linked to any OSDs)
        AlbaController.checkup_maintenance_agents()
        services = []
        for alba_node, maintenance_info in ManagerClientMockup.maintenance_agents.iteritems():
            alba_node.invalidate_dynamics('maintenance_services')
            if alba_backend_2.name in alba_node.maintenance_services:
                services.append(maintenance_info)
                self.assertEqual(first=1, second=len(maintenance_info))
                self.assertEqual(first=[alba_node.node_id], second=maintenance_info.values()[0])
        self.assertEqual(first=1, second=len(services))  # Only 1 service should have been deployed for the 2nd ALBA Backend