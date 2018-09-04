# Copyright (C) 2018 iNuron NV
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
from ovs.dal.hybrids.albas3transactioncluster import S3TransactionCluster
from ovs.dal.hybrids.service import Service


class S3TransactionService(DataObject):
    """
    Represent the junction between the S3Transaction cluster and all its services.
    A service can represent any cluster and a cluster can have multiple services representing it
    Each ALBA ABM cluster can have several ABM services which each represent an ALBA Manager Arakoon cluster.
    This ABM cluster has 1 service representing a node of the ALBA Manager Arakoon cluster.
    """
    __properties = []
    __relations = [Relation('s3_transaction_cluster', S3TransactionCluster, 's3_transaction_services'),
                   Relation('service', Service, 's3_transaction_service', onetoone=True)]
    __dynamics = []
