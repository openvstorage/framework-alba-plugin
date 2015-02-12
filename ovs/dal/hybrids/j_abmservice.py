# Copyright 2014 CloudFounders NV
# All rights reserved

"""
NSMService module
"""
from ovs.dal.dataobject import DataObject
from ovs.dal.structures import Property, Relation
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.service import Service


class ABMService(DataObject):
    """
    The ABMService class represents the junction table between the (albamanager)Service and AlbaBackend.
    Examples:
    * my_alba_backend.abm_services[0].service
    * my_service.abm_service.alba_backend
    """
    __properties = []
    __relations = [Relation('alba_backend', AlbaBackend, 'abm_services'),
                   Relation('service', Service, 'abm_service', onetoone=True)]
    __dynamics = []
