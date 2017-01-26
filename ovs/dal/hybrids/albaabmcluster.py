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
ABMCluster module
"""
from ovs.dal.dataobject import DataObject
from ovs.dal.structures import Property, Relation
from ovs.dal.hybrids.albabackend import AlbaBackend


class ABMCluster(DataObject):
    """
    The ABMCluster class represents the relation between an ALBA Backend and the ABM services.
    Each ALBA Backend has 1 ABM cluster.
    This ABM cluster has several services representing the nodes of the ALBA Manager Arakoon cluster.
    Examples:
    * my_alba_backend.abm_cluster.abm_services
    * my_service.abm_service.abm_cluster.alba_backend
    """
    __properties = [Property('name', str, unique=True, doc='Name of the ALBA Manager Arakoon cluster'),
                    Property('config_location', str, unique=True, doc='Location of the ALBA Manager Arakoon configuration')]
    __relations = [Relation('alba_backend', AlbaBackend, 'abm_cluster', onetoone=True)]
    __dynamics = []
