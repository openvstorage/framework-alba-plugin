# Copyright 2014 CloudFounders NV
# All rights reserved

"""
AlbaBackend module
"""
from ovs.dal.dataobject import DataObject
from ovs.dal.hybrids.backend import Backend
from ovs.dal.structures import Property, Relation


class AlbaBackend(DataObject):
    """
    The AlbaBackend provides ALBA specific information
    """
    __properties = [Property('accesskey', str, doc='ALBA backend access key')]
    __relations = [Relation('backend', Backend, 'alba_backend', onetoone=True, doc='Linked generic backend')]
    __dynamics = []
