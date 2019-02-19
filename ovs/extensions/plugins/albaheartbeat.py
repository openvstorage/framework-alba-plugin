# Copyright (C) 2018 iNuron NV
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
import time
import random
import logging
from threading import Thread
from ovs.constants.albalogging import HEARTBEAT_LOGGER
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.lists.albanodeclusterlist import AlbaNodeClusterList
from ovs.extensions.generic.configuration import Configuration
from ovs_extensions.generic.configuration import NoLockAvailableException
from ovs_extensions.generic.ipmi import IPMIController
from ovs.extensions.generic.sshclient import SSHClient


class AlbaHeartBeat(object):
    """
    Heartbeat class. Responsible for checking the state of OSDs within a Dual Controller
    """

    _logger = logging.getLogger(HEARTBEAT_LOGGER)
    _client = SSHClient('127.0.0.1', username='root')

    @classmethod
    def poll_node_osds_state(cls):
        # type: () -> None
        """
        Polling system to check the states of AlbaNodes
        Runs in a locker context to avoid querying Alba too often
        When the lock is taken: fetch the state of the OSDs for all AlbaNode that are part of a Cluster
        When the state is too dire -> initiate a failover towards another node in that cluster
        :return: None
        :rtype: NoneType
        """
        try:
            threads = []
            with Configuration.lock('albanodes_osd_state', wait=5, expiration=60):
                for node_cluster in AlbaNodeClusterList.get_alba_node_clusters():
                    for node in node_cluster.albanodes:
                        device_summary = node.local_summary['devices']
                        if len(device_summary['green'] + device_summary['warning']) < len(device_summary['red']):
                            # @todo to offload to celery or not...
                            # Offloading so the polling lock can be released faster
                            thread = Thread(target=cls.initiate_failover, args=(node.guid,))
                            thread.start()
                            threads.append(thread)
            for thread in threads:
                thread.join()
        except NoLockAvailableException:
            cls._logger.info('Unable to acquire the lock')

    @classmethod
    def initiate_failover(cls, node_guid):
        # type: (basestring) -> None
        """
        Initiate an OSD failover for a particular AlbaNode
        This AlbaNode has to be part of an AlbaNodeCluster with multiple AlbaNodes
        :param node_guid: Guid of the AlbaNode
        :type node_guid: basestring
        :return: None
        :rtype: NoneType
        """
        with Configuration.lock('albanode_{0}_failover'.format(node_guid), wait=5, expiration=60):
            node = AlbaNode(node_guid)
            node_cluster = node.albanode_cluster
            if node_cluster is None:
                raise ValueError('Unable to failover Node with guid {0} as it has no relation to a cluster'.format(node_guid))
            other_node_guids = [guid for guid in node.albanode_cluster.albanode_guids if guid != node_guid]
            if len(other_node_guids) == 0:
                raise ValueError('Unable to failover Node with guid {0} as there are no failover candidates'.format(node_guid))
            while len(other_node_guids) > 0:
                # Select random failover node from the pool
                failover_node = AlbaNode(other_node_guids.pop(random.randrange(len(other_node_guids))))
                cls._logger.info('Checking if Node with guid {0} is responsive so a failover can happen'.format(failover_node.guid))
                success = False
                count = 0
                while success is False:
                    count += 1
                    if count > 3:
                        cls._logger.error('Node with guid {0} is not responsive. Looking for another node'.format(failover_node.guid))
                        break
                    try:
                        failover_node.client.get_metadata()
                        success = True
                        continue  # Avoid sleep
                    except:
                        cls._logger.exception('Node with guid {0} is not responsive'.format(failover_node.guid))
                    time.sleep(5)
                if success is False:
                    # Another node must be selected
                    continue
                # Kill current node through IPMI
                ipmi_info = node.ipmi_info
                try:
                    ipmi_controller = IPMIController(client=cls._client, **ipmi_info)
                    ipmi_controller.power_off_node()
                except:
                    cls._logger.exception('Unable to control node with guid {0} through IPMI'.format(node_guid))

        raise RuntimeError('No failover happened. Exhausted all options')
