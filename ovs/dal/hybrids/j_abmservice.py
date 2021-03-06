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
ABMService module
"""
from ovs.dal.dataobject import DataObject
from ovs.dal.structures import Relation
from ovs.dal.hybrids.albaabmcluster import ABMCluster
from ovs.dal.hybrids.service import Service


class ABMService(DataObject):
    """
    The ABMService class represents the junction table between the (ALBA Manager)Service and the ALBA Manager Arakoon cluster.
    Each ALBA ABM cluster can have several ABM services which each represent an ALBA Manager Arakoon cluster.
    This ABM cluster has 1 service representing a node of the ALBA Manager Arakoon cluster.
    Examples:
    * my_alba_backend.abm_cluster.abm_services
    * my_service.abm_service.abm_cluster.alba_backend
    """
    __properties = []
    __relations = [Relation('abm_cluster', ABMCluster, 'abm_services'),
                   Relation('service', Service, 'abm_service', onetoone=True)]
    __dynamics = []
