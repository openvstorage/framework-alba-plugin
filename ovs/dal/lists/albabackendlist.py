# Copyright 2014 Open vStorage NV
# All rights reserved

"""
AlbaBackendList module
"""
from ovs.dal.datalist import DataList
from ovs.dal.dataobject import DataObjectList
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.helpers import Descriptor


class AlbaBackendList(object):
    """
    This AlbaBackendList class contains various lists regarding to the AlbaBackend class
    """

    @staticmethod
    def get_albabackends():
        """
        Returns a list of all ALBABackends
        """
        backends = DataList({'object': AlbaBackend,
                             'data': DataList.select.GUIDS,
                             'query': {'type': DataList.where_operator.AND,
                                       'items': []}}).data
        return DataObjectList(backends, AlbaBackend)

    @staticmethod
    def get_by_alba_id(alba_id):
        """
        Gets an AlbaBackend by the alba_id
        """
        backends = DataList({'object': AlbaBackend,
                          'data': DataList.select.GUIDS,
                          'query': {'type': DataList.where_operator.AND,
                                    'items': [('alba_id', DataList.operator.EQUALS, alba_id)]}}).data
        if len(backends) == 1:
            return Descriptor(AlbaBackend, backends[0]).get_object(True)
        return None
