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
AlbaNode module
"""
import requests
from ovs.dal.dataobject import DataObject
from ovs.dal.hybrids.storagerouter import StorageRouter
from ovs.dal.structures import Dynamic, Property, Relation
from ovs.extensions.generic.configuration import Configuration
from ovs.extensions.plugins.asdmanager import ASDManagerClient, InvalidCredentialsError


class AlbaNode(DataObject):
    """
    The AlbaNode contains information about nodes (containing OSDs)
    """
    __properties = [Property('ip', str, unique=True, doc='IP Address'),
                    Property('port', int, doc='Port'),
                    Property('node_id', str, unique=True, doc='Alba node_id identifier'),
                    Property('username', str, doc='Username of the AlbaNode'),
                    Property('password', str, doc='Password of the AlbaNode'),
                    Property('type', ['ASD'], default='ASD', doc='The type of the AlbaNode'),
                    Property('package_information', dict, mandatory=False, default={}, doc='Information about installed packages and potential available new versions')]
    __relations = [Relation('storagerouter', StorageRouter, 'alba_node', onetoone=True, mandatory=False, doc='StorageRouter hosting the AlbaNode')]
    __dynamics = [Dynamic('storage_stack', dict, 5),
                  Dynamic('ips', list, 3600)]

    def __init__(self, *args, **kwargs):
        """
        Initializes an AlbaNode, setting up its additional helpers
        """
        DataObject.__init__(self, *args, **kwargs)
        self._frozen = False
        self.client = ASDManagerClient(self)
        self._frozen = True

    def _storage_stack(self):
        """
        Returns a live list of all disks known to this AlbaNode
        """
        storage_stack = {'status': 'ok',
                         'stack': {}}
        stack = storage_stack['stack']

        try:
            disk_data = self.client.get_disks()
        except (requests.ConnectionError, requests.Timeout, InvalidCredentialsError):
            storage_stack['status'] = 'nodedown'
            disk_data = {}
        partition_device_map = {}
        for disk_id, disk_info in disk_data.iteritems():
            entry = {'name': disk_id,
                     'asds': {}}
            entry.update(disk_info)
            if disk_info['state'] == 'ok':
                entry['status'] = 'uninitialized' if disk_info['available'] is True else 'initialized'
                entry['status_detail'] = ''
            else:
                entry['status'] = disk_info['state']
                entry['status_detail'] = disk_info.get('state_detail', '')
            stack[disk_id] = entry
            if 'partition_aliases' in disk_info:
                for partition_alias in disk_info['partition_aliases']:
                    partition_device_map[partition_alias] = disk_id
            else:
                partition_device_map[disk_id] = disk_id

        # Model Disk information
        for disk in self.disks:
            found = False
            for disk_id, disk_info in stack.iteritems():
                if any(alias in disk.aliases for alias in disk_info['aliases']):
                    found = True
            if found is False and len(disk.aliases) > 0:
                disk_id = disk.aliases[0].split('/')[-1]
                stack[disk_id] = {'available': False,
                                  'name': disk_id,
                                  'asds': {},
                                  'status': 'error',
                                  'status_detail': 'missing',
                                  'aliases': disk.aliases,
                                  'device': disk.aliases[0],
                                  'partition_aliasses': [],
                                  'node_id': self.node_id}

        # Live ASD information
        try:
            asd_data = self.client.get_asds()
        except (requests.ConnectionError, requests.Timeout, InvalidCredentialsError):
            storage_stack['status'] = 'nodedown'
            asd_data = {}
        for partition_id, asds in asd_data.iteritems():
            if partition_id not in partition_device_map:
                continue
            disk_id = partition_device_map.get(partition_id)
            if disk_id is not None and disk_id in stack:
                for asd_id, asd_info in asds.iteritems():
                    stack[disk_id]['asds'][asd_id] = {'asd_id': asd_id,
                                                      'status': 'error' if asd_info['state'] == 'error' else 'initialized',
                                                      'status_detail': asd_info.get('state_detail', ''),
                                                      'state': asd_info['state'],
                                                      'state_detail': asd_info.get('state_detail', '')}
        return storage_stack

    def _ips(self):
        """
        Returns the IPs of the node
        """
        return Configuration.get('/ovs/alba/asdnodes/{0}/config/network|ips'.format(self.node_id))
