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
from ovs_extensions.generic.exceptions import InvalidCredentialsError
from ovs.extensions.plugins.albacli import AlbaCLI, AlbaError
from ovs.extensions.plugins.asdmanager import ASDManagerClient
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
                  Dynamic('supported_osd_types', list, 3600),
                  Dynamic('read_only_mode', bool, 60),
                  Dynamic('local_summary', dict, 3600)]

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
        from ovs.dal.lists.albabackendlist import AlbaBackendList

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

        model_osds = {}
        for osd in self.osds:
            if osd.slot_id not in stack:
                stack[osd.slot_id] = {'status': 'missing' if node_status is None else node_status,
                                      'osds': {}}
            osd_info = stack[osd.slot_id]['osds'].get(osd.osd_id, {})
            osd_info.update(osd.stack_info)
            stack[osd.slot_id]['osds'][osd.osd_id] = osd_info
            model_osds[osd.osd_id] = osd

        for slot_info in stack.itervalues():
            for osd_id, osd in slot_info['osds'].iteritems():
                if osd_id not in model_osds or self.type == AlbaNode.NODE_TYPES.GENERIC:
                    # The is known by the remote node but not in the model OR it's a generic node
                    # In that case, let's connect to the OSD to see whether we get some info from it
                    try:
                        if osd_id in model_osds:
                            ips = model_osds[osd_id].ips
                            port = model_osds[osd_id].port
                        else:
                            # TODO: Check impact once https://github.com/openvstorage/alba/issues/773 lands
                            ips = osd['ips']
                            port = osd['port']
                        # TODO: Function call below should be executed only once when https://github.com/openvstorage/alba/issues/783 is solved
                        claimed_by = 'unknown'
                        for ip in ips:
                            try:
                                claimed_by = AlbaCLI.run('get-osd-claimed-by', named_params={'host': ip, 'port': port})
                                break
                            except (AlbaError, RuntimeError):
                                AlbaNode._logger.warning('get-osd-claimed-by failed for IP:port {0}:{1}'.format(ip, port))
                        if claimed_by == 'unknown':
                            raise

                        alba_backend = AlbaBackendList.get_by_alba_id(claimed_by)
                        osd['claimed_by'] = alba_backend.guid if alba_backend is not None else claimed_by
                    except KeyError:
                        osd['claimed_by'] = 'unknown'
                    except:
                        AlbaNode._logger.exception('Could not load OSD info: {0}'.format(osd_id))
                        osd['claimed_by'] = 'unknown'
                        if osd.get('status') not in ['error', 'warning']:
                            osd['status'] = 'error'
                            osd['status_detail'] = 'unreachable'
                        raise
        if self.type == AlbaNode.NODE_TYPES.GENERIC:
            # Add prefix of 2 digits based on amount of slots on this ALBA node for sorting in GUI
            slot_amount = len(set(osd.slot_id for osd in self.osds))
            prefix = '{0:02d}'.format(slot_amount)
            slot_id = '{0}{1}'.format(prefix, str(uuid.uuid4())[2:])
            stack[slot_id] = {'status': 'empty'}
        return stack

    def _node_metadata(self):
        """
        Returns a set of metadata hinting on how the Node should be used
        """
        slots_metadata = {'fill': False,  # Prepare Slot for future usage
                          'fill_add': False,  # OSDs will added and claimed right away
                          'clear': False}  # Indicates whether OSDs can be removed from ALBA Node / Slot
        if self.type == AlbaNode.NODE_TYPES.ASD:
            slots_metadata.update({'fill': True,
                                   'fill_metadata': {'count': 'integer'},
                                   'clear': True})
        elif self.type == AlbaNode.NODE_TYPES.GENERIC:
            slots_metadata.update({'fill_add': True,
                                   'fill_add_metadata': {'osd_type': 'osd_type',
                                                         'ips': 'list_of_ip',
                                                         'port': 'port'},
                                   'clear': True})

        return slots_metadata

    def _supported_osd_types(self):
        """
        Returns a list of all supported OSD types
        """
        from ovs.dal.hybrids.albaosd import AlbaOSD
        if self.type == AlbaNode.NODE_TYPES.GENERIC:
            return [AlbaOSD.OSD_TYPES.ASD, AlbaOSD.OSD_TYPES.AD]
        if self.type == AlbaNode.NODE_TYPES.ASD:
            return [AlbaOSD.OSD_TYPES.ASD]

    def _read_only_mode(self):
        """
        Indicates whether the ALBA Node can be used for OSD manipulation
        If the version on the ALBA Node is lower than a specific version required by the framework, the ALBA Node becomes read only,
        this means, that actions such as creating, restarting, deleting OSDs becomes impossible until the node's software has been updated
        :return: True if the ALBA Node should be read only, False otherwise
        :rtype: bool
        """
        return self.client.get_metadata()['_version'] < 3  # Version 3 was introduced when Slots for Active Drives have been introduced

    def _local_summary(self):
        """
        Return a summary of the osds
        :return:
        """
        device_info = {'red': 0,
                       'green': 0,
                       'orange': 0}
        local_summary = {'devices': device_info}  # For future additions?
        for slot_id, slot_data in self.stack.iteritems():
            if slot_data.get('status', 'empty') == 'empty':
                continue
            for osd_id, osd_data in slot_data['osds'].iteritems():
                status = osd_data.get('status', 'unknown')
                if status == 'ok':
                    device_info['green'] += 1
                elif status == 'warning':
                    device_info['orange'] += 1
                elif status == 'error':
                    device_info['red'] += 1
        return local_summary
