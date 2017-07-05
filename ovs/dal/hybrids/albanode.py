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
import re
import uuid
import requests
from ovs.dal.dataobject import DataObject
from ovs.dal.hybrids.storagerouter import StorageRouter
from ovs.dal.structures import Dynamic, Property, Relation
from ovs.extensions.generic.configuration import Configuration
from ovs.extensions.plugins.asdmanager import ASDManagerClient, InvalidCredentialsError
from ovs.extensions.plugins.genericmanager import GenericManagerClient


class AlbaNode(DataObject):
    """
    The AlbaNode contains information about nodes (containing OSDs)
    """
    NODE_TYPES = DataObject.enumerator('NodeType', ['ASD', 'GENERIC'])

    __properties = [Property('ip', str, indexed=True, mandatory=False, doc='IP Address'),
                    Property('port', int, mandatory=False, doc='Port'),
                    Property('node_id', str, unique=True, indexed=True, doc='Alba node_id identifier'),
                    Property('username', str, mandatory=False, doc='Username of the AlbaNode'),
                    Property('password', str, mandatory=False, doc='Password of the AlbaNode'),
                    Property('type', NODE_TYPES.keys(), default=NODE_TYPES.ASD, doc='The type of the AlbaNode'),
                    Property('package_information', dict, mandatory=False, default={}, doc='Information about installed packages and potential available new versions')]
    __relations = [Relation('storagerouter', StorageRouter, 'alba_node', onetoone=True, mandatory=False, doc='StorageRouter hosting the AlbaNode')]
    __dynamics = [Dynamic('storage_stack', dict, 15, locked=True),
                  Dynamic('stack', dict, 15, locked=True),
                  Dynamic('ips', list, 3600),
                  Dynamic('maintenance_services', dict, 30, locked=True),
                  Dynamic('metadata', dict, 3600),
                  Dynamic('supported_osd_types', list, 3600)]

    def __init__(self, *args, **kwargs):
        """
        Initializes an AlbaNode, setting up its additional helpers
        """
        DataObject.__init__(self, *args, **kwargs)
        self._frozen = False
        self.client = None
        if self.type == AlbaNode.NODE_TYPES.ASD:
            self.client = ASDManagerClient(self)
        if self.type == AlbaNode.NODE_TYPES.GENERIC:
            self.client = GenericManagerClient(self)
        self._frozen = True

    def _storage_stack(self):
        """
        Returns a live list of all disks known to this AlbaNode
        """
        # @todo Support multiple clients and fetching from the by slots: {slot_id: {1,2,3}}
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
                                  'partition_aliases': [],
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

    def _maintenance_services(self):
        """
        Returns all maintenance services on this node, grouped by backend name 
        """
        services = {}
        try:
            for service_name in self.client.list_maintenance_services():
                match = re.match('^alba-maintenance_(.*)-[a-zA-Z0-9]{16}$', service_name)
                if match is not None:
                    service_status = self.client.get_service_status(name=service_name)
                    backend_name = match.groups()[0]
                    if backend_name not in services:
                        services[backend_name] = []
                    services[backend_name].append([service_name, service_status])
        except:
            pass
        return services

    def _stack(self):
        """
        Returns an overview of this node's storage stack
        """
        stack = {}
        try:
            remote_stack = self.client.get_stack()
            for slot_id, slot_data in remote_stack.iteritems():
                stack[slot_id] = {'status': 'ok'}
                stack[slot_id].update(slot_data)
            for osd in self.osds:
                if osd.slot_id not in stack:
                    stack[osd.slot_id] = {'status': 'missing',
                                          'osds': {}}
                osd_info = stack[osd.slot_id]['osds'].get(osd.osd_id, {})
                osd_info.update(osd.stack_info)
                stack[osd.slot_id]['osds'][osd.slot_id] = osd_info
            # TODO: Enrich the osds with live data from Alba, if required
        except:
            pass  # TODO: Handle errors a bit better here
        if self.type == AlbaNode.NODE_TYPES.GENERIC:
            stack[str(uuid.uuid4())] = {'status': 'empty'}
        return stack

    def _metadata(self):
        """
        Returns a set of metadata hinting on how the Node should be used
        """
        slots_metadata = {'fill': False,
                          'fill_add': False}
        if self.type == AlbaNode.NODE_TYPES.ASD:
            slots_metadata.update({'fill': True,
                                   'fill_metadata': {'count': 'integer'}})
        if self.type == AlbaNode.NODE_TYPES.GENERIC:
            slots_metadata.update({'fill_add': True,
                                   'fill_add_metadata': {'type': 'osd_type'}})

        return {'slots': slots_metadata}

    def _supported_osd_types(self):
        """
        Returns a list of all supported OSD types
        """
        from ovs.dal.hybrids.albaosd import AlbaOSD
        if self.type == AlbaNode.NODE_TYPES.GENERIC:
            return [AlbaOSD.OSD_TYPES.ASD, AlbaOSD.OSD_TYPES.AD]
        if self.type == AlbaNode.NODE_TYPES.ASD:
            return [AlbaOSD.OSD_TYPES.ASD]
