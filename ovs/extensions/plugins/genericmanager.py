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

from ovs.extensions.generic.logger import Logger


class GenericManagerClient(object):
    """
    Generic Manager Client
    Used by AD OSDs. No API implementation for this type yet.
    """

    def __init__(self, node):
        self._logger = Logger('extensions-plugins')
        self.node = node

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

    def fill_slot(self, slot_id, extra):
        """
        Pretends to fill a slot with a set of osds
        """
        _ = self, slot_id, extra
        pass

    def restart_osd(self, slot_id, osd_id):
        """
        Pretends to restart an OSD.
        """
        _ = self, slot_id, osd_id
        return {'_success': True}

    def restart_slot(self, slot_id):
        """
        Pretends to restart a slot
        """
        _ = self, slot_id
        return {'_success': True}

    def stop_slot(self, slot_id):
        """
        Pretends to stop a slot
        """
        _ = self, slot_id
        return {'_success': True}

    def delete_osd(self, slot_id, osd_id):
        """
        Pretends to delete the OSD from the Slot
        """
        _ = self, slot_id, osd_id
        return {'_success': True}

    def build_slot_params(self, osd):
        """
        Builds the "extra" params for replacing an OSD
        """
        _ = self, osd
        return {}

    def get_metadata(self):
        """
        Gets metadata from the node
        """
        _ = self
        return {'_version': 3}

    def sync_stack(self, stack):
        """
        Synchronize the stack of an AlbaNode with the stack of another AlbaNode
        :param stack: Stack to sync
        :return: None
        :rtype: Nonetype
        """
        _ = stack
        return None
