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

import os
import re
import requests
from ovs.constants.albanode import ASD_NODE_CONFIG_PATH, S3_NODE_CONFIG_PATH
from ovs.dal.dataobject import DataObject
from ovs.dal.hybrids.albanodecluster import AlbaNodeCluster
from ovs.dal.hybrids.storagerouter import StorageRouter
from ovs.dal.structures import Dynamic, Property, Relation
from ovs.extensions.generic.configuration import Configuration, NotFoundException
from ovs_extensions.generic.exceptions import InvalidCredentialsError
from ovs.extensions.generic.logger import Logger
from ovs.extensions.plugins.albacli import AlbaCLI, AlbaError
from ovs.extensions.plugins.asdmanager import ASDManagerClient
from ovs.extensions.plugins.genericmanager import GenericManagerClient
from ovs.extensions.plugins.s3manager import S3ManagerClient
from ovs.extensions.plugins.tests.alba_mockups import ManagerClientMockup


class AlbaNode(DataObject):
    """
    The AlbaNode contains information about nodes (containing OSDs)
    """
    NODE_TYPES = DataObject.enumerator('NodeType', ['ASD', 'GENERIC', 'S3'])
    OSD_STATUSES = DataObject.enumerator('OSDStatus', {'ERROR': 'error',
                                                       'MISSING': 'missing',
                                                       'OK': 'ok',
                                                       'UNAVAILABLE': 'unavailable',
                                                       'UNKNOWN': 'unknown',
                                                       'WARNING': 'warning'})
    OSD_STATUS_DETAILS = DataObject.enumerator('OSDStatusDetail', {'ACTIVATING': 'service_activating',
                                                                   'ALBAERROR': 'albaerror',
                                                                   'DECOMMISSIONED': 'decommissioned',
                                                                   'ERROR': 'recenterrors',
                                                                   'NODEDOWN': 'nodedown',
                                                                   'UNREACHABLE': 'unreachable'})
    SLOT_STATUSES = DataObject.enumerator('SlotStatus', {'OK': 'ok',
                                                         'WARNING': 'warning',
                                                         'MISSING': 'missing',
                                                         'UNAVAILABLE': 'unavailable',
                                                         'UNKNOWN': 'unknown',
                                                         'EMPTY': 'empty'})
    CLIENTS = DataObject.enumerator('AlbaNodeClients', {NODE_TYPES.ASD: ASDManagerClient,
                                                        NODE_TYPES.GENERIC: GenericManagerClient,
                                                        NODE_TYPES.S3: S3ManagerClient})
    CONFIG_LOCATIONS = DataObject.enumerator('AlbaNodeConfigLocations', {NODE_TYPES.ASD: ASD_NODE_CONFIG_PATH,
                                                                         NODE_TYPES.GENERIC: '',
                                                                         NODE_TYPES.S3: S3_NODE_CONFIG_PATH})

    _logger = Logger('hybrids')
    __properties = [Property('ip', str, indexed=True, mandatory=False, doc='IP Address'),
                    Property('port', int, mandatory=False, doc='Port'),
                    Property('node_id', str, unique=True, indexed=True, doc='Alba node_id identifier'),
                    Property('name', str, mandatory=False, doc='Optional name for the AlbaNode'),
                    Property('username', str, mandatory=False, doc='Username of the AlbaNode'),
                    Property('password', str, mandatory=False, doc='Password of the AlbaNode'),
                    Property('type', NODE_TYPES.keys(), default=NODE_TYPES.ASD, doc='The type of the AlbaNode'),
                    Property('package_information', dict, mandatory=False, default={}, doc='Information about installed packages and potential available new versions')]
    __relations = [Relation('storagerouter', StorageRouter, 'alba_node', onetoone=True, mandatory=False, doc='StorageRouter hosting the Alba Node'),
                   Relation('alba_node_cluster', AlbaNodeCluster, 'alba_nodes', mandatory=False, doc='The Alba Node Cluster to which the Alba Node belongs')]
    __dynamics = [Dynamic('stack', dict, 15, locked=True),
                  Dynamic('ips', list, 3600),
                  Dynamic('maintenance_services', dict, 30, locked=True),
                  Dynamic('node_metadata', dict, 3600),
                  Dynamic('supported_osd_types', list, 3600),
                  Dynamic('read_only_mode', bool, 60),
                  Dynamic('local_summary', dict, 60),
                  Dynamic('ipmi_info', dict, 3600)]

    def __init__(self, *args, **kwargs):
        """
        Initializes an AlbaNode, setting up its additional helpers
        """
        DataObject.__init__(self, *args, **kwargs)
        self._frozen = False
        self.client = None
        if os.environ.get('RUNNING_UNITTESTS') == 'True':
            self.client = ManagerClientMockup(self)
        else:
            if self.type not in self.CLIENTS:
                raise NotImplementedError('Type {0} is not implemented'.format(self.type))
            self.client = self.CLIENTS[self.type](self)
        self._frozen = True

    def _ips(self):
        """
        Returns the IPs of the node
        """
        return Configuration.get(os.path.join(self.CONFIG_LOCATIONS[self.type], 'network|ips').format(self.node_id))

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
        node_down = False
        # Fetch stack from asd-manager
        try:
            remote_stack = self.client.get_stack()
            for slot_id, slot_data in remote_stack.iteritems():
                stack[slot_id] = {'status': 'ok'}
                stack[slot_id].update(slot_data)
                # Migrate state > status
                _move(stack[slot_id])
                for osd_data in slot_data.get('osds', {}).itervalues():
                    _move(osd_data)
        except (requests.ConnectionError, requests.Timeout, InvalidCredentialsError):
            node_down = True

        model_osds = {}
        found_osds = {}
        # Apply own model to fetched stack
        for osd in self.osds:
            model_osds[osd.osd_id] = osd  # Initially set the info
            if osd.slot_id not in stack:
                stack[osd.slot_id] = {'status': self.OSD_STATUSES.UNKNOWN if node_down is True else self.OSD_STATUSES.MISSING,
                                      'status_detail': self.OSD_STATUS_DETAILS.NODEDOWN if node_down is True else '',
                                      'osds': {}}
            osd_data = stack[osd.slot_id]['osds'].get(osd.osd_id, {})
            stack[osd.slot_id]['osds'][osd.osd_id] = osd_data  # Initially set the info in the stack
            osd_data.update(osd.stack_info)
            if node_down is True:
                osd_data['status'] = self.OSD_STATUSES.UNKNOWN
                osd_data['status_detail'] = self.OSD_STATUS_DETAILS.NODEDOWN
            elif osd.alba_backend_guid is not None:  # Osds has been claimed
                # Load information from alba
                if osd.alba_backend_guid not in found_osds:
                    found_osds[osd.alba_backend_guid] = {}
                    if osd.alba_backend.abm_cluster is not None:
                        config = Configuration.get_configuration_path(osd.alba_backend.abm_cluster.config_location)
                        try:
                            for found_osd in AlbaCLI.run(command='list-all-osds', config=config):
                                found_osds[osd.alba_backend_guid][found_osd['long_id']] = found_osd
                        except (AlbaError, RuntimeError):
                            self._logger.exception('Listing all osds has failed')
                            osd_data['status'] = self.OSD_STATUSES.UNKNOWN
                            osd_data['status_detail'] = self.OSD_STATUS_DETAILS.ALBAERROR
                            continue

                if osd.osd_id not in found_osds[osd.alba_backend_guid]:
                    # Not claimed by any backend thus not in use
                    continue
                found_osd = found_osds[osd.alba_backend_guid][osd.osd_id]
                if found_osd['decommissioned'] is True:
                    osd_data['status'] = self.OSD_STATUSES.UNAVAILABLE
                    osd_data['status_detail'] = self.OSD_STATUS_DETAILS.DECOMMISSIONED
                    continue

                backend_interval_key = '/ovs/alba/backends/{0}/gui_error_interval'.format(osd.alba_backend_guid)
                if Configuration.exists(backend_interval_key):
                    interval = Configuration.get(backend_interval_key)
                else:
                    interval = Configuration.get('/ovs/alba/backends/global_gui_error_interval')
                read = found_osd['read'] or [0]
                write = found_osd['write'] or [0]
                errors = found_osd['errors']
                osd_data['status'] = self.OSD_STATUSES.WARNING
                osd_data['status_detail'] = self.OSD_STATUS_DETAILS.ERROR
                if len(errors) == 0 or (len(read + write) > 0 and max(min(read), min(write)) > max(error[0] for error in errors) + interval):
                    osd_data['status'] = self.OSD_STATUSES.OK
                    osd_data['status_detail'] = ''

        for slot_info in stack.itervalues():
            for osd_id, osd in slot_info['osds'].iteritems():
                if osd.get('status_detail') == self.OSD_STATUS_DETAILS.ACTIVATING:
                    osd['claimed_by'] = 'unknown'  # We won't be able to connect to it just yet
                    continue
                if osd_id not in model_osds:
                    # The osd is known by the remote node but not in the model
                    # In that case, let's connect to the OSD to see whether we get some info from it
                    try:
                        ips = osd['hosts'] if 'hosts' in osd and len(osd['hosts']) > 0 else osd.get('ips', [])
                        port = osd['port']
                        claimed_by = 'unknown'
                        for ip in ips:
                            try:
                                # Output will be None if it is not claimed
                                claimed_by = AlbaCLI.run('get-osd-claimed-by',
                                                         named_params={'host': ip, 'port': port})
                                break
                            except (AlbaError, RuntimeError):
                                AlbaNode._logger.warning('get-osd-claimed-by failed for IP:port {0}:{1}'.format(ip, port))
                        alba_backend = AlbaBackendList.get_by_alba_id(claimed_by)
                        osd['claimed_by'] = alba_backend.guid if alba_backend is not None else claimed_by
                    except KeyError:
                        osd['claimed_by'] = 'unknown'
                    except:
                        AlbaNode._logger.exception('Could not load OSD info: {0}'.format(osd_id))
                        osd['claimed_by'] = 'unknown'
                        if osd.get('status') not in ['error', 'warning']:
                            osd['status'] = self.OSD_STATUSES.ERROR
                            osd['status_detail'] = self.OSD_STATUS_DETAILS.UNREACHABLE
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
        elif self.type == AlbaNode.NODE_TYPES.S3:
            slots_metadata.update({'fill_add': True,
                                   'fill_add_metadata': {'count': 'integer',
                                                         'osd_type': 'osd_type',
                                                         'buckets': 'list_of_string'},
                                   'clear': True})
        return slots_metadata

    def _supported_osd_types(self):
        """
        Returns a list of all supported OSD types
        """
        from ovs.dal.hybrids.albaosd import AlbaOSD
        if self.type == AlbaNode.NODE_TYPES.GENERIC:
            return [AlbaOSD.OSD_TYPES.ASD, AlbaOSD.OSD_TYPES.AD]
        elif self.type == AlbaNode.NODE_TYPES.ASD:
            return [AlbaOSD.OSD_TYPES.ASD]
        elif self.type == AlbaNode.NODE_TYPES.S3:
            return []
        return []

    def _read_only_mode(self):
        """
        Indicates whether the ALBA Node can be used for OSD manipulation
        If the version on the ALBA Node is lower than a specific version required by the framework, the ALBA Node becomes read only,
        this means, that actions such as creating, restarting, deleting OSDs becomes impossible until the node's software has been updated
        :return: True if the ALBA Node should be read only, False otherwise
        :rtype: bool
        """
        read_only = False
        if self.type in [AlbaNode.NODE_TYPES.GENERIC, AlbaNode.NODE_TYPES.ASD]:
            try:
                read_only = self.client.get_metadata()['_version'] < 3
            except (requests.ConnectionError, requests.Timeout, InvalidCredentialsError):
                pass  # When down, nothing can be edited.
        return read_only  # Version 3 was introduced when Slots for Active Drives have been introduced

    def _local_summary(self):
        """
        Return a summary of the OSDs based on their state
        * Ok -> green
        * WARNING -> orange
        * ERROR -> red
        * UNKNOWN -> gray
        The summary will contain a list of dicts with guid, osd_id and claimed_by
        eg:
        {'red': [{osd_id: 1, claimed_by: alba_backend_guid1}],
         'green': [{osd_id: 2, claimed_by: None}],
          ...}
        :return: Summary of the OSDs filtered by status (which are represented by color)
        """
        device_info = {'red': [],
                       'green': [],
                       'orange': [],
                       'gray': []}
        local_summary = {'devices': device_info}  # For future additions?
        state_map = {self.OSD_STATUSES.OK: 'green',
                     self.OSD_STATUSES.WARNING: 'orange',
                     self.OSD_STATUSES.ERROR: 'red',
                     self.OSD_STATUSES.UNKNOWN: 'gray'}
        for slot_id, slot_data in self.stack.iteritems():
            for osd_id, osd_data in slot_data.get('osds', {}).iteritems():
                status = osd_data.get('status', self.OSD_STATUSES.UNKNOWN)
                osd_info = {'claimed_by': osd_data.get('claimed_by'),
                            'osd_id': osd_data.get('osd_id')}
                if status in state_map:  # Can never be too sure
                    device_info[state_map[status]].append(osd_info)
        return local_summary

    def _ipmi_info(self):
        """
        Retrieve the IPMI information of the AlbaNode
        :return: Dict with ipmi information
        :rtype: dict
        """
        try:
            return Configuration.get(os.path.join(self.CONFIG_LOCATIONS[self.type], 'ipmi').format(self.node_id))
        except NotFoundException:  # Could be that the ASDManager does not yet have the IPMI info stored
            return {'ip': None,
                    'username': None,
                    'password': None}
