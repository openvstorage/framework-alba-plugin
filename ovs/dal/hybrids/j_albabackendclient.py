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
AlbaBackendUser module
"""
from ovs.dal.dataobject import DataObject
from ovs.dal.structures import Property, Relation
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.client import Client


class AlbaBackendClient(DataObject):
    """
    The AlbaBackendUser class represents the junction table between a Client and AlbaBackend, setting granted/deny rights
    Examples:
    * my_alba_backend.client_rights[0].client
    * my_client.albabackend_rights[0].alba_backend
    """
    __properties = [Property('grant', bool, doc='Whether the rights is granted (True) or denied (False)')]
    __relations = [Relation('alba_backend', AlbaBackend, 'client_rights'),
                   Relation('client', Client, 'albabackend_rights')]
    __dynamics = []
