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
from ovs.dal.hybrids.albansmcluster import NSMCluster
from ovs.dal.hybrids.service import Service


class NSMService(DataObject):
    """
    The NSMService class represents the junction table between the (Namespace Manager)Service and AlbaBackend.
    Each ALBA NSM cluster can have several NSM services which each represent a Namespace Manager Arakoon cluster.
    Each NSM service has 1 service representing a node of a Namespace Manager Arakoon cluster.
    Examples:
    * my_alba_backend.nsm_clusters[0].nsm_services
    * my_service.nsm_service.nsm_cluster.alba_backend
    """
    __properties = []
    __relations = [Relation('nsm_cluster', NSMCluster, 'nsm_services'),
                   Relation('service', Service, 'nsm_service', onetoone=True)]
    __dynamics = []
