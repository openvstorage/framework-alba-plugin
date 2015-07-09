# Copyright 2014 Open vStorage NV
# All rights reserved

"""
AlbaNodeList module
"""
from ovs.dal.datalist import DataList
from ovs.dal.dataobject import DataObjectList
from ovs.dal.helpers import Descriptor
from ovs.dal.hybrids.albanode import AlbaNode


class AlbaNodeList(object):
    """
    This AlbaNodeList class contains various lists regarding to the AlbaNode class
    """

    @staticmethod
    def get_albanodes():
        """
        Returns a list of all AlbaNodes
        """
        nodes = DataList({'object': AlbaNode,
                          'data': DataList.select.GUIDS,
                          'query': {'type': DataList.where_operator.AND,
                                    'items': []}}).data
        return DataObjectList(nodes, AlbaNode)

    @staticmethod
    def get_albanode_by_ip(ip):
        """
        Returns a node by ip
        """
        nodes = DataList({'object': AlbaNode,
                          'data': DataList.select.GUIDS,
                          'query': {'type': DataList.where_operator.AND,
                                    'items': [('ip', DataList.operator.EQUALS, ip)]}}).data
        if len(nodes) == 1:
            return Descriptor(AlbaNode, nodes[0]).get_object(True)
        return None

    @staticmethod
    def get_albanode_by_box_id(box_id):
        """
        Returns a node by its box_id
        """
        nodes = DataList({'object': AlbaNode,
                          'data': DataList.select.GUIDS,
                          'query': {'type': DataList.where_operator.AND,
                                    'items': [('box_id', DataList.operator.EQUALS, box_id)]}}).data
        if len(nodes) == 1:
            return Descriptor(AlbaNode, nodes[0]).get_object(True)
        return None
