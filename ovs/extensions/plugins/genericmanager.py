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

    def add_osd(self, ip, port, alba_backend_guid):
        """
        add osd to manager so it could be claimed later.
        :param ip: ip address of the osd
        :param port: port of the osd
        :param alba_backend_guid: guid of the albabackend to add the osd too
        :return: information about the osd
        """
        from ovs.dal.hybrids.albabackend import AlbaBackend
        alba_backend = AlbaBackend(alba_backend_guid)
        # @todo implement alba calls here
        # @The osd should be registered to each albabackend so be able to claim it from either one
        config = Configuration.get_configuration_path(key=alba_backend.abm_cluster.config_location)
        import uuid
        osd_info = {'osd_id': str(uuid.uuid4())}
        # osd_info = AlbaCLI.run('add-osd', config=config, named_params={'host': ip, 'port': port})
        return osd_info

    def get_disks(self):
        # @Todo implement this behaviour
        return {}

    def get_asds(self):
        # @todo implement this
        return {}
