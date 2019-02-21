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

import logging
from ovs.dal.tests.alba_helpers import AlbaDalHelper
from ovs.extensions.generic.configuration import Configuration
from ovs_extensions.log.logger import Logger
from ovs.extensions.plugins.tests.alba_mockups import ManagerClientMockup, VirtualAlbaBackend
from ovs_extensions.testing.testcase import LogTestCase
from ovs.lib.alba import AlbaController


class AlbaGeneric(LogTestCase):
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
        with self.assertLogs(level=logging.DEBUG) as logging_watcher:
            AlbaController.checkup_maintenance_agents()
        logs = logging_watcher.get_message_severity_map()
        self.assertIn(member=log_entry, container=logs.keys())
        self.assertEqual(first='WARNING', second=logs[log_entry])

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
        log_entry = 'Layout does not contain any known/reachable nodes and will be ignored'
        Configuration.set(key=config_key, value=[unknown_node_name])  # Only unknown Nodes in layout
        with self.assertLogs(level=logging.DEBUG) as logging_watcher:
            AlbaController.checkup_maintenance_agents()
        logs = logging_watcher.get_message_severity_map()
        self.assertIn(member=log_entry, container=logs.keys())
        self.assertEqual(first='WARNING', second=logs[log_entry])
        self.assertIn(member=alba_node, container=ManagerClientMockup.maintenance_agents)  # The ALBA Node linked to the ALBA Backend should again have the maintenance agent
        self.assertEqual(first=1, second=len(ManagerClientMockup.maintenance_agents[alba_node]))  # Only 1 maintenance agent should have been deployed
        self.assertEqual(first=[alba_node.node_id],
                         second=ManagerClientMockup.maintenance_agents[alba_node].values()[0])  # Read preference must be the Node ID of the Node on which the maintenance was deployed

        # 3 out of 4 ALBA Nodes do not have a maintenance agent yet
        alba_nodes_wo_agent = [an for an in alba_structure['alba_nodes'].itervalues() if an != alba_node_w_agent_1]
        self.assertEqual(first=3, second=len(alba_nodes_wo_agent))

        #############################################
        # Verify at least 1 known ALBA Node in layout
        node_3 = alba_structure['alba_nodes'][3]
        log_entry = 'Layout contains unknown/unreachable node {0}'.format(unknown_node_name)
        Configuration.set(key=config_key, value=[unknown_node_name, node_3.node_id])  # 1 known ALBA Node in layout
        with self.assertLogs(level=logging.DEBUG) as logging_watcher:
            AlbaController.checkup_maintenance_agents()
        logs = logging_watcher.get_message_severity_map()
        self.assertIn(member=log_entry, container=logs.keys())
        self.assertEqual(first='WARNING', second=logs[log_entry])
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
