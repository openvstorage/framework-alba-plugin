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
from ovs.dal.hybrids.albaosd import AlbaOSD


class AlbaOSDList(object):
    """
    This AlbaBackendList class contains various lists regarding to the AlbaBackend class
    """

    @staticmethod
    def get_albaosds():
        """
        Returns a list of all ALBABackends
        :rtype: list[ovs.dal.hybrids.albaosd.AlbaOSD]
        """
        return DataList(AlbaOSD, {'type': DataList.where_operator.AND,
                                  'items': []})

    @staticmethod
    def get_by_osd_id(osd_id):
        """
        Gets an AlbaBackend by the alba_id
        :rtype: ovs.dal.hybrids.albaosd.AlbaOSD
        """
        backends = DataList(AlbaOSD, {'type': DataList.where_operator.AND,
                                      'items': [('osd_id', DataList.operator.EQUALS, osd_id)]})
        if len(backends) == 1:
            return backends[0]
        return None
