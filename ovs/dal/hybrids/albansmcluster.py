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
NSMCluster module
"""
from ovs.dal.dataobject import DataObject
from ovs.dal.structures import Property, Relation
from ovs.dal.hybrids.albabackend import AlbaBackend


class NSMCluster(DataObject):
    """
    The ABMCluster class represents the relation between an ALBA Backend and the Namespace Manager services.
    Each ALBA Backend has at least 1 Namespace Manager Arakoon cluster.
    Each NSM cluster has several services representing the nodes of the ALBA Namespace Manager Arakoon cluster.
    Examples:
    * my_alba_backend.nsm_clusters[0].nsm_services
    * my_service.nsm_service.nsm_cluster.alba_backend
    """
    __properties = [Property('name', str, unique=True, doc='Name of the ALBA Namespace Manager Arakoon cluster'),
                    Property('number', int, doc='The number of the service in case there is more than one'),
                    Property('capacity', int, default=50, doc='The capacity of this NSM, negative means infinite'),
                    Property('config_location', str, unique=True, doc='Location of the ALBA Namespace Manager Arakoon configuration')]
    __relations = [Relation('alba_backend', AlbaBackend, 'nsm_clusters')]
    __dynamics = []
