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
AlbaBackendList module
"""
from ovs.dal.datalist import DataList
from ovs.dal.hybrids.albabackend import AlbaBackend


class AlbaBackendList(object):
    """
    This AlbaBackendList class contains various lists regarding to the AlbaBackend class
    """

    @staticmethod
    def get_albabackends():
        """
        Returns a list of all ALBABackends
        :rtype: list[ovs.dal.hybrids.albabackend.AlbaBackend]
        """
        return DataList(AlbaBackend, {'type': DataList.where_operator.AND,
                                      'items': []})

    @staticmethod
    def get_by_alba_id(alba_id):
        """
        Gets an AlbaBackend by the alba_id
        :rtype: ovs.dal.hybrids.albabackend.AlbaBackend
        """
        backends = DataList(AlbaBackend, {'type': DataList.where_operator.AND,
                                          'items': [('alba_id', DataList.operator.EQUALS, alba_id)]})
        if len(backends) > 1:
            raise RuntimeError('Multiple ALBA Backends found with alba_id {0}'.format(alba_id))
        if len(backends) == 1:
            return backends[0]
        return None
