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
        # type: (AlbaNode, int) -> None
        """
        Initialize a base clients. Creates an API client with an AlbaNode
        :param node: The AlbaNode to create the API client for
        :param timeout: Call timeout in seconds
        :return: None
        :rtype: NoneType
        """
        self.node = node
        credentials = (self.node.username, self.node.password)
        super(AlbaBaseClient, self).__init__(self.node.ip, self.node.port, credentials, timeout)

    # Metadata
    def get_metadata(self, *args, **kwargs):
        # type: (*any, **any) -> dict
        """
        Gets metadata from the node
        :return: Dict with metadata
        :rtype: dict
        """
        raise NotImplementedError()

    # Osds
    def restart_osd(self, slot_id, osd_id, *args, **kwargs):
        # type: (str, str, *any, **any) -> None
        """
        Restart an OSD.
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :param osd_id: Identifier of the OSD
        :type osd_id: str
        :return: None
        :rtype: NoneType
        """
        raise NotImplementedError()

    def delete_osd(self, slot_id, osd_id, *args, **kwargs):
        # type: (str, str, *any, **any) -> None
        """
        Delete the OSD from the Slot
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :param osd_id: Identifier of the OSD
        :type osd_id: str
        :return: None
        :rtype: NoneType
        """
        raise NotImplementedError()

    # Slots
    def fill_slot(self, slot_id, extra, *args, **kwargs):
        # type: (str, dict, *any, **any) -> None
        """
        Fill a slot with a set of osds
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :param extra: Extra parameters to account for
        :type extra: dict
        :return: None
        :rtype: NoneType
        """
        raise NotImplementedError()

    def restart_slot(self, slot_id, *args, **kwargs):
        # type: (str, *any, **any) -> None
        """
        Restart a slot
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :return: None
        :rtype: NoneType
        """
        raise NotImplementedError()

    def stop_slot(self, slot_id, *args, **kwargs):
        # type: (str, *any, **any) -> None
        """
        Stop a slot. This will cause all OSDs on that slot to stop
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :return: None
        :rtype: NoneType
        """
        raise NotImplementedError()

    def clear_slot(self, slot_id, *args, **kwargs):
        # type: (str, *any, **any) -> None
        """
        Clears the slot
        :param slot_id: Identifier of the slot to clear
        :type slot_id: str
        :return: None
        :rtype: NoneType
        """
        raise NotImplementedError()

    def build_slot_params(self, osd, *args, **kargs):
        # type: (any, *any, **any) -> dict
        """
        Builds the "extra" params for replacing an OSD
        :param osd: The OSD object
        :type osd: any
        :return: The extra param used in the create osd code
        :rtype: dict
        """
        raise NotImplementedError()

    # Stack
    def get_stack(self, *args, **kwargs):
        # type: (*any, **any) -> dict
        """
        Returns the node's stack
        :return: Dict with stack information
        :rtype: dict
        """
        raise NotImplementedError()

    def sync_stack(self, stack, *args, **kwargs):
        # type: (dict, *any, **any) -> None
        """
        Synchronize the stack of an AlbaNode with the stack of another AlbaNode
        :param stack: Stack to sync
        :type stack: dict
        :return: None
        :rtype: Nonetype
        """
        raise NotImplementedError()
