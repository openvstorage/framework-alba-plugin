# Copyright (C) 2017 iNuron NV
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
Generic module for calling the Generic Manager. Well, sort off, since it's a dummy manager
"""

from ovs.extensions.plugins.albabase import AlbaBaseClient


class GenericManagerClient(AlbaBaseClient):
    """
    Generic Manager Client
    Used by AD OSDs. No API implementation for this type yet.
    """

    def __init__(self, node, timeout=None):
        # type: (ovs.dal.hybrids.albanode.AlbaNode, int) -> None
        super(GenericManagerClient, self).__init__(node, timeout)

    def _call(self, *args, **kwargs):
        raise RuntimeError('The generic Manager client does not use an API yet')

    def get_stack(self):
        """
        Returns the generic node's stack
        """
        stack = {}
        for osd in self.node.osds:
            if osd.slot_id not in stack:
                stack[osd.slot_id] = {'state': 'ok',
                                      'available': False,
                                      'osds': {}}
            stack_info = osd.stack_info
            stack_info['status'] = 'ok'
            stack[osd.slot_id]['osds'][osd.osd_id] = stack_info
        return stack

    def fill_slot(self, slot_id, extra, *args, **kwargs):
        # type: (str, dict, *any, **any) -> None
        """
        Pretends to fill a slot with a set of osds
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :param extra: Extra parameters to account for
        :type extra: dict
        :return: None
        :rtype: NoneType
        """
        _ = self, slot_id, extra

    def restart_osd(self, slot_id, osd_id, *args, **kwargs):
        # type: (str, str, *any, **any) -> None
        """
        Pretends to restart an OSD.
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :param osd_id: Identifier of the OSD
        :type osd_id: str
        :return: None
        :rtype: NoneType
        """
        _ = self, slot_id, osd_id

    def restart_slot(self, slot_id, *args, **kwargs):
        # type: (str, *any, **any) -> None
        """
        Pretends to restart a slot
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :return: None
        :rtype: NoneType
        """
        _ = self, slot_id

    def clear_slot(self, slot_id, *args, **kwargs):
        # type: (str, *any, **any) -> None
        """
        Pretends to clears the slot
        :param slot_id: Identifier of the slot to clear
        :type slot_id: str
        :return: None
        :rtype: NoneType
        """
        _ = self, slot_id

    def stop_slot(self, slot_id, *args, **kwargs):
        # type: (str, *any, **any) -> None
        """
        Pretends to stop a slot. This will cause all OSDs on that slot to stop
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :return: None
        :rtype: NoneType
        """
        _ = self, slot_id

    def delete_osd(self, slot_id, osd_id, *args, **kwargs):
        # type: (str, str, *any, **any) -> None
        """
        Pretends to delete the OSD from the Slot
        :param slot_id: Identifier of the slot
        :type slot_id: str
        :param osd_id: Identifier of the OSD
        :type osd_id: str
        :return: None
        :rtype: NoneType
        """
        _ = self, slot_id, osd_id

    def build_slot_params(self, osd, *args, **kargs):
        # type: (any, *any, **any) -> dict
        """
        Builds the "extra" params for replacing an OSD
        :param osd: The OSD object
        :type osd: any
        :return: The extra param used in the create osd code
        :rtype: dict
        """
        _ = self, osd
        return {}

    def get_metadata(self):
        """
        Gets metadata from the node
        """
        _ = self
        return {'_version': 3}

    def sync_stack(self, stack, *args, **kwargs):
        # type: (dict, *any, **any) -> None
        """
        Synchronize the stack of an AlbaNode with the stack of another AlbaNode
        :param stack: Stack to sync
        :type stack: dict
        :return: None
        :rtype: Nonetype
        """
        _ = stack
        return None
