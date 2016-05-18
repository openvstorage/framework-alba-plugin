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
                    Property('capacity', int, default=50, doc='The capacity of this MDS, negative means infinite')]
    __relations = [Relation('alba_backend', AlbaBackend, 'nsm_services'),
                   Relation('service', Service, 'nsm_service', onetoone=True)]
    __dynamics = []
