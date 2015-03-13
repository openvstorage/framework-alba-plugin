# Copyright 2014 CloudFounders NV
# All rights reserved

"""
AlbaNode module
"""
from ovs.dal.dataobject import DataObject
from ovs.dal.structures import Property, Relation
from ovs.dal.hybrids.storagerouter import StorageRouter


class AlbaNode(DataObject):
    """
    The AlbaNode contains information about nodes (containing OSDs)
    """
    __properties = [Property('ip', str, doc='IP Address'),
                    Property('port', int, doc='Port'),
                    Property('box_id', str, doc='Alba box_id identifier'),
                    Property('username', str, doc='Username of the AlbaNode, if applicable'),
                    Property('password', str, doc='Password of the AlbaNode, if applicable'),
                    Property('disks', list, mandatory=False, doc='Placeholder for disks (semi-dynamic/persistent)'),
                    Property('ips', list, mandatory=False, doc='Placeholder for ips (semi-dynamic/persistent)'),
                    Property('type', ['ASD', 'SUPERMICRO'], default='ASD', doc='The type of the AlbaNode')]
    __relations = [Relation('storagerouter', StorageRouter, 'alba_nodes', mandatory=False, doc='StorageRouter hosting the AlbaNode')]
    __dynamics = []
