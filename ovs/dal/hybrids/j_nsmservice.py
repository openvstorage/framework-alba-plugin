# Copyright 2014 Open vStorage NV
# All rights reserved

"""
NSMService module
"""
from ovs.dal.dataobject import DataObject
from ovs.dal.structures import Property, Relation
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.service import Service


class NSMService(DataObject):
    """
    The NSMService class represents the junction table between the (namespacemanager)Service and AlbaBackend.
    Examples:
    * my_alba_backend.nsm_services[0].service
    * my_service.nsm_service.alba_backend
    """
    __properties = [Property('number', int, doc='The number of the service in case there are more than one'),
                    Property('capacity', int, default=-1, doc='The capacity of this MDS, negative means infinite')]
    __relations = [Relation('alba_backend', AlbaBackend, 'nsm_services'),
                   Relation('service', Service, 'nsm_service', onetoone=True)]
    __dynamics = []
