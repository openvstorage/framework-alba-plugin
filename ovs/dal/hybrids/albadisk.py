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
AlbaDisk module
"""
from ovs.dal.dataobject import DataObject
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.structures import Property, Relation


class AlbaDisk(DataObject):
    """
    The AlbaDisk represents a disk hosting zero or more ASDs
    """
    __properties = [Property('name', str, doc='The disk name')]
    __relations = [Relation('alba_node', AlbaNode, 'disks', doc='The AlbaNode to which the AlbaDisk belongs')]
    __dynamics = []
