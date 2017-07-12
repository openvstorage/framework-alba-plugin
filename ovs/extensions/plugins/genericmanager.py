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
from ovs.extensions.generic.configuration import Configuration
# from ovs.extensions.plugins.albacli import AlbaCLI
from ovs.log.log_handler import LogHandler


class InvalidCredentialsError(RuntimeError):
    """
    Invalid credentials error
    """
    pass


class NotFoundError(RuntimeError):
    """
    Method not found error
    """
    pass


class GenericManagerClient(object):
    """
    Generic Manager Client
    """

    def __init__(self, node):
        self._logger = LogHandler.get('extensions', name='genericmanagerclient')
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
            stack[osd.slot_id]['osds'][osd.osd_id] = osd.stack_info
        return stack

    def fill_slot(self, slot_id, extra):
        """
        Fills a slot with a set of osds
        """
        _ = self, slot_id, extra
        # This basically doesn't have to do anything. The generic node only supports fill + add, so the asds will be
        # added and claimed anyway. This always results in the OSDs being in the model.
        pass
