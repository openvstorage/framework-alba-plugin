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
from ovs.dal.structures import Relation
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
