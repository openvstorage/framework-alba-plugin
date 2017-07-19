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
from ovs.extensions.plugins.albacli import AlbaCLI
from ovs.extensions.plugins.asdmanager import ASDManagerClient, InvalidCredentialsError
from ovs.extensions.plugins.genericmanager import GenericManagerClient
from ovs.log.log_handler import LogHandler


class AlbaNode(DataObject):
    """
    The AlbaNode contains information about nodes (containing OSDs)
    """
    NODE_TYPES = DataObject.enumerator('NodeType', ['ASD', 'GENERIC'])
    _logger = LogHandler.get('dal', name='hybrid')

    __properties = [Property('ip', str, indexed=True, mandatory=False, doc='IP Address'),
                    Property('port', int, mandatory=False, doc='Port'),
                    Property('node_id', str, unique=True, indexed=True, doc='Alba node_id identifier'),
                    Property('name', str, mandatory=False, doc='Optional name for the AlbaNode'),
                    Property('username', str, mandatory=False, doc='Username of the AlbaNode'),
                    Property('password', str, mandatory=False, doc='Password of the AlbaNode'),
                    Property('type', NODE_TYPES.keys(), default=NODE_TYPES.ASD, doc='The type of the AlbaNode'),
                    Property('package_information', dict, mandatory=False, default={}, doc='Information about installed packages and potential available new versions')]
    __relations = [Relation('storagerouter', StorageRouter, 'alba_node', onetoone=True, mandatory=False, doc='StorageRouter hosting the AlbaNode')]
    __dynamics = [Dynamic('stack', dict, 15, locked=True),
                  Dynamic('ips', list, 3600),
                  Dynamic('maintenance_services', dict, 30, locked=True),
                  Dynamic('node_metadata', dict, 3600),
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
        def _move(info):
            for move in [('state', 'status'),
                         ('state_detail', 'status_detail')]:
                if move[0] in info:
                    info[move[1]] = info[move[0]]
                    del info[move[0]]

        stack = {}
        node_status = None
        try:
            remote_stack = self.client.get_stack()
            for slot_id, slot_data in remote_stack.iteritems():
                stack[slot_id] = {'status': 'ok'}
                stack[slot_id].update(slot_data)
                # Migrate state > status
                _move(stack[slot_id])
                for osd_info in slot_data.get('osds', {}).itervalues():
                    _move(osd_info)
        except (requests.ConnectionError, requests.Timeout, InvalidCredentialsError):
            node_status = 'nodedown'

        model_ids = []
        for osd in self.osds:
            if osd.slot_id not in stack:
                stack[osd.slot_id] = {'status': 'missing' if node_status is None else node_status,
                                      'osds': {}}
            osd_info = stack[osd.slot_id]['osds'].get(osd.osd_id, {})
            osd_info.update(osd.stack_info)
            stack[osd.slot_id]['osds'][osd.osd_id] = osd_info
            model_ids.append(osd.osd_id)

        for slot_info in stack.itervalues():
            for osd_id, osd in slot_info['osds'].iteritems():
                if osd_id not in model_ids or self.type == AlbaNode.NODE_TYPES.GENERIC:
                    # The is known by the remote node but not in the model OR it's a generic node
                    # In that case, let's connect to the OSD to see whether we get some info from it
                    try:
                        host = osd['hosts'][0] if 'hosts' in osd else osd['ips'][0]
                        osd['claimed_by'] = AlbaCLI.run('get-osd-claimed-by', named_params={'host': host,
                                                                                            'port': osd['port']})
                    except KeyError:
                        osd['claimed_by'] = 'unknown'
                    except:
                        AlbaNode._logger.exception('Could not load OSD info: {0}'.format(osd_id))
                        osd['claimed_by'] = 'unknown'
                        if osd.get('status') not in ['error', 'warning']:
                            osd['status'] = 'error'
                            osd['status_detail'] = 'unreachable'
        if self.type == AlbaNode.NODE_TYPES.GENERIC:
            stack[str(uuid.uuid4())] = {'status': 'empty'}
        return stack

    def _node_metadata(self):
        """
        Returns a set of metadata hinting on how the Node should be used
        """
        slots_metadata = {'fill': False,
                          'fill_add': False,
                          'clear': False}
        if self.type == AlbaNode.NODE_TYPES.ASD:
            slots_metadata.update({'fill': True,
                                   'fill_metadata': {'count': 'integer'},
                                   'clear': True})
        if self.type == AlbaNode.NODE_TYPES.GENERIC:
            slots_metadata.update({'fill_add': True,
                                   'fill_add_metadata': {'osd_type': 'osd_type',
                                                         'ip': 'ip',
                                                         'port': 'port'},
                                   'clear': True})

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
