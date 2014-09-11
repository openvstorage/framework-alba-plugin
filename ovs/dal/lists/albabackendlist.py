# Copyright 2014 CloudFounders NV
# All rights reserved

"""
AlbaBackendList module
"""
from ovs.dal.datalist import DataList
from ovs.dal.dataobject import DataObjectList
from ovs.dal.hybrids.albabackend import AlbaBackend


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
