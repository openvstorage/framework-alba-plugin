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
Generic module for calling the ASD-Manager
"""

from ovs.extensions.plugins.apiclient import APIClient


class AlbaBaseClient(APIClient):
    """
    Base Alba Manager Client
    """

    def __init__(self, node, timeout=None):
        self.node = node
        credentials = (self.node.username, self.node.password)
        super(AlbaBaseClient, self).__init__(self.node.ip, self.node.port, credentials, timeout)

    # Metadata
    def get_metadata(self):
        """
        Gets metadata from the node
        """
        raise NotImplementedError()

    # Osds
    def restart_osd(self, slot_id, osd_id):
        """
        Restart an OSD.
        """
        raise NotImplementedError()

    def delete_osd(self, slot_id, osd_id):
        """
        Delete the OSD from the Slot
        """
        raise NotImplementedError()

    # Slots
    def fill_slot(self, slot_id, extra):
        """
        Fill a slot with a set of osds
        """
        raise NotImplementedError()

    def restart_slot(self, slot_id):
        """
        Restart a slot
        """
        raise NotImplementedError()

    def stop_slot(self, slot_id):
        """
        Stop a slot
        """
        raise NotImplementedError()

    def build_slot_params(self, osd):
        """
        Builds the "extra" params for replacing an OSD
        """
        raise NotImplementedError()

    # Stack
    def get_stack(self):
        """
        Returns the node's stack
        """
        raise NotImplementedError()

    def sync_stack(self, stack):
        """
        Synchronize the stack of an AlbaNode with the stack of another AlbaNode
        :param stack: Stack to sync
        :return: None
        :rtype: Nonetype
        """
        raise NotImplementedError()
