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
AlbaController module
"""

import os
import re
import time
import string
import random
import requests
from ovs.dal.exceptions import ObjectNotFoundException
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.hybrids.albaosd import AlbaOSD
from ovs.dal.hybrids.backend import Backend
from ovs.dal.hybrids.domain import Domain
from ovs.dal.hybrids.storagerouter import StorageRouter
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.albaosdlist import AlbaOSDList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs_extensions.api.client import OVSClient
from ovs.extensions.db.arakooninstaller import ArakoonClusterConfig, ArakoonInstaller
from ovs.extensions.generic.configuration import Configuration, NotFoundException
from ovs.extensions.generic.logger import Logger
from ovs.extensions.generic.sshclient import SSHClient, UnableToConnectException
from ovs_extensions.generic.toolbox import ExtensionsToolbox
from ovs.extensions.migration.migration.albamigrator import ExtensionMigrator
from ovs.extensions.plugins.albacli import AlbaCLI, AlbaError
from ovs.extensions.storage.volatilefactory import VolatileFactory
from ovs.lib.helpers.decorators import add_hooks, ovs_task
from ovs.lib.helpers.toolbox import Schedule
from ovs.lib.albaarakoon import AlbaArakoonController


class DecommissionedException(Exception):
    def __init__(self, *args):
        super(DecommissionedException, self).__init__(*args)


class AlbaController(object):
    """
    Contains all BLL related to ALBA
    """
    ABM_PLUGIN = 'albamgr_plugin'
    NSM_PLUGIN = 'nsm_host_plugin'

    ARAKOON_PLUGIN_DIR = '/usr/lib/alba'
    CONFIG_ALBA_BACKEND_KEY = '/ovs/alba/backends/{0}'
    NR_OF_AGENTS_CONFIG_KEY = '/ovs/alba/backends/{0}/maintenance/nr_of_agents'
    AGENTS_LAYOUT_CONFIG_KEY = '/ovs/alba/backends/{0}/maintenance/agents_layout'
    CONFIG_DEFAULT_NSM_HOSTS_KEY = CONFIG_ALBA_BACKEND_KEY.format('default_nsm_hosts')

    _logger = Logger('lib')

    @staticmethod
    @ovs_task(name='alba.update_osds')
    def update_osds(osds, alba_node_guid):
        """
        Update OSDs that are already registered on an ALBA Backend.
        Currently used to update the IPs or node ID on which the OSD should be exposed
        :param osds: List of OSD information objects [ [osd_id, osd_data],  ]
        :type osds: list
        :param alba_node_guid: Guid of the ALBA Node on which the OSDs reside
        :type alba_node_guid: str
        :return: OSDs that could not be updated
        :rtype: list
        """
        # Validation
        osds_to_process = []
        validation_reasons = []
        for osd_id, osd_data in osds:
            AlbaController._logger.debug('OSD with ID {0}: Verifying information'.format(osd_id))
            try:
                ExtensionsToolbox.verify_required_params(required_params={'ips': (list, ExtensionsToolbox.regex_ip, False),
                                                                          'node_id': (str, None, False)},
                                                         actual_params=osd_data)
            except RuntimeError as ex:
                validation_reasons.append(str(ex))
                continue

            requested_ips = osd_data.get('ips')
            requested_node_id = osd_data.get('node_id')
            if requested_ips is None and requested_node_id is None:
                continue  # Nothing to do

            osd = AlbaOSDList.get_by_osd_id(osd_id)
            if osd is None:
                validation_reasons.append('OSD with ID {0} has not yet been registered.'.format(osd_id))
                continue

            if requested_node_id is not None:
                requested_node = AlbaNodeList.get_albanode_by_node_id(requested_node_id)
                if requested_node is None:
                    validation_reasons.append('OSD with ID {0} cannot be added to node with ID {1} because the node does not exist'.format(osd_id, requested_node_id))
                else:
                    node_osd_ids = [osd_id for slot_data in requested_node.stack.values() for osd_id in slot_data['osds'].keys()]
                    if osd_id not in node_osd_ids:
                        validation_reasons.append('OSD with ID {0} is not a part of the requested node with ID {1}'.format(osd_id, requested_node_id))

            if requested_ips is not None and requested_ips == osd.ips:
                AlbaController._logger.info('OSD with ID {0} already has the requested IPs configured: {1}'.format(osd_id, ', '.join(osd.ips)))

            if osd.osd_type == AlbaOSD.OSD_TYPES.ALBA_BACKEND:
                validation_reasons.append('OSD with ID {0} is of type {1} and cannot be updated.'.format(osd_id, osd.osd_type))

            osd_data['object'] = osd
            osds_to_process.append([osd_id, osd_data])

        alba_node = AlbaNode(alba_node_guid)
        if len(validation_reasons) > 0:
            raise ValueError('- {0}'.format('\n- '.join(validation_reasons)))

        # Processing
        failures = []
        for osd_id, osd_data in osds_to_process:
            AlbaController._logger.debug('OSD with ID {0}: Updating'.format(osd_id))
            requested_ips = osd_data.get('ips')
            requested_node_id = osd_data.get('node_id')
            osd = osd_data['object']
            orig_ips = osd.ips
            config_location = Configuration.get_configuration_path(key=osd.alba_backend.abm_cluster.config_location)
            AlbaController._logger.debug('OSD with ID {0}: Updating on ALBA'.format(osd_id))
            try:
                alba_node.client.update_osd(slot_id=osd.slot_id,
                                            osd_id=osd.osd_id,
                                            update_data={'ips': requested_ips})
            except Exception:
                AlbaController._logger.exception('OSD with ID {0}: Failed to update IPs via asd-manager'.format(osd_id))
                failures.append(osd_id)
                continue
            if requested_ips is not None:
                try:
                    AlbaCLI.run(command='update-osd', config=config_location, named_params={'long-id': osd_id,
                                                                                            'ip': ','.join(requested_ips)})
                except AlbaError:
                    AlbaController._logger.exception('OSD with ID {0}: Failed to update IPs via ALBA'.format(osd_id))
                    failures.append(osd_id)
                    continue

            # Node ID is stored under the ASD Config

            AlbaController._logger.debug('OSD with ID {0}: Updating in model'.format(osd_id))
            try:
                if requested_ips is not None:
                    osd.ips = requested_ips
                if requested_node_id is not None:
                    osd.alba_node = AlbaNodeList.get_albanode_by_node_id(requested_node_id)
                osd.save()
            except Exception:
                failures.append(osd_id)
                try:  # Updated in ALBA, so try to revert config in ALBA, because model is out of sync
                    AlbaCLI.run(command='update-osd', config=config_location, named_params={'long-id': osd_id, 'ip': ','.join(orig_ips)})
                except AlbaError:
                    AlbaController._logger.exception('OSD with ID {0}: Failed to revert OSD IPs from new IPs {1} to original IPs {2}'.format(osd_id, ', '.join(requested_ips), ', '.join(orig_ips)))
        return failures

    @staticmethod
    @ovs_task(name='alba.add_osds')
    def add_osds(alba_backend_guid, osds, alba_node_guid=None, metadata=None):
        """
        Adds and claims an OSD to the Backend
        :param alba_backend_guid: Guid of the ALBA Backend
        :type alba_backend_guid: str
        :param osds: OSDs to add to the ALBA Backend
        :type osds: list[dict]
        :param alba_node_guid: Guid of the ALBA Node (None in case of other Backends as OSDs)
        :type alba_node_guid: str
        :param metadata: Metadata to add to the OSD (connection information for remote Backend, general Backend information)
        :type metadata: dict
        :raises RuntimeError: - When parameters are missing
                              - When the Backend does not have an ABM registered
                              - When No maintenance services have been deployed
                              - When some or all OSDs could not be claimed
        :return: OSDs that have not been claimed
        :rtype: list
        """
        # Validate OSD information
        backend_osds = []
        generic_osds = []  # Both AD and ASD fit under here
        validation_reasons = []
        for osd in osds:
            try:
                osd_list = backend_osds
                required = {'osd_type': (str, AlbaOSD.OSD_TYPES.keys())}
                if osd.get('osd_type') != AlbaOSD.OSD_TYPES.ALBA_BACKEND:
                    osd_list = generic_osds
                    required.update({'ips': (list, ExtensionsToolbox.regex_ip),
                                     'port': (int, {'min': 1, 'max': 65535}),
                                     'slot_id': (str, None)})
                ExtensionsToolbox.verify_required_params(required_params=required, actual_params=osd)
                osd_list.append(osd)
            except RuntimeError as ex:
                validation_reasons.append(str(ex))
        # Validate ALBA Backend properly configured
        alba_backend = AlbaBackend(alba_backend_guid)
        if alba_backend.abm_cluster is None:
            validation_reasons.append('ALBA Backend {0} does not have an ABM cluster registered'.format(alba_backend.name))

        # Validate maintenance setup properly
        service_deployed = False
        for alba_node in AlbaNodeList.get_albanodes():
            try:
                for service_name in alba_node.client.list_maintenance_services():
                    if re.match('^alba-maintenance_{0}-[a-zA-Z0-9]{{16}}$'.format(alba_backend.name), service_name):
                        service_deployed = True
                        break
            except:
                pass
            if service_deployed is True:
                break
        if service_deployed is False:
            validation_reasons.append('No maintenance agents have been deployed for ALBA Backend {0}'.format(alba_backend.name))

        if len(generic_osds) > 0 and alba_node_guid is None:
            validation_reasons.append('The OSDs are not linked to an AlbaNode')

        if len(validation_reasons) > 0:
            raise RuntimeError('- {0}'.format('\n- '.join(validation_reasons)))

        # Process
        domain = None
        domain_guid = metadata['backend_info'].get('domain_guid') if metadata is not None else None
        if domain_guid is not None:
            try:
                domain = Domain(domain_guid)
            except ObjectNotFoundException:
                AlbaController._logger.warning('Provided Domain with guid {0} has been deleted in the meantime'.format(domain_guid))

        # Register OSDs according to type
        failed = []
        unclaimed = []
        if len(generic_osds) > 0:
            failed_generic, unclaimed_generic = AlbaController._add_generic_osds(alba_backend_guid=alba_backend_guid,
                                                                                 alba_node_guid=alba_node_guid,
                                                                                 osds=generic_osds,
                                                                                 domain=domain,
                                                                                 metadata=metadata)
            failed.extend(failed_generic)
            unclaimed.extend(unclaimed_generic)
        if len(backend_osds) > 0:
            failed_backend, unclaimed_backend = AlbaController._add_backend_osds(alba_backend_guid=alba_backend_guid,
                                                                                 osds=backend_osds,
                                                                                 domain=domain,
                                                                                 metadata=metadata)
            failed.extend(failed_backend)
            unclaimed.extend(unclaimed_backend)
        if len(failed) > 0:
            if len(failed) == len(osds):
                raise RuntimeError('None of the requested OSDs could be claimed')
            else:
                raise RuntimeError('Some of the requested OSDs could not be claimed: {0}'.format(', '.join(failed)))
        return unclaimed

    @staticmethod
    def _add_backend_osds(alba_backend_guid, osds, domain, metadata):
        """
        Adds and claims an OSD of type Backend
        Currently only supports linking one at the time due to the metadata aspect being sent only for a single OSD
        :param alba_backend_guid: Guid of the ALBA Backend
        :type alba_backend_guid: str
        :param osds: Information about the OSD. Eg: [{111111: {'osd_type': 'ALBA_BACKEND'}}]
        :type osds: list[dict]
        :param domain: Domain to which the OSDs should be linked
        :type domain: ovs.dal.hybrids.domain.Domain
        :param metadata: Metadata related to the OSD
        :type metadata: dict
        :raises RuntimeError: - When metadata cannot be found
                              - When no preset are found or if no presets are available
        :raises DecommissionedException: - When the Backend to link its state is decommissioned
        :return: OSDs which failed to be added and/or claimed and OSD that were not claimed
        :rtype: tuple
        """
        alba_backend = AlbaBackend(alba_backend_guid)
        config = Configuration.get_configuration_path(key=alba_backend.abm_cluster.config_location)

        failure_osds = []
        unclaimed_osds = []
        for _ in osds:  # Currently only one OSD can be added at once of type local Backend
            # Verify OSD has already been added
            is_available = False
            is_claimed = False
            linked_alba_id = metadata['backend_info']['linked_alba_id']  # Also the osd_id
            for available_osd in AlbaCLI.run(command='list-all-osds', config=config):
                if available_osd.get('long_id') == linked_alba_id:
                    if available_osd.get('decommissioned') is True:
                        raise DecommissionedException('{0} is decommissioned.'.format(linked_alba_id))
                    is_available = True
                    is_claimed = available_osd.get('alba_id') is not None
            if is_claimed is False and is_available is False:
                # Add the OSD
                # Retrieve remote Arakoon configuration
                preset_name = str(metadata['backend_info']['linked_preset'])
                connection_info = metadata['backend_connection_info']
                ovs_client = OVSClient.get_instance(connection_info=connection_info, cache_store=VolatileFactory.get_client())
                backend_info = ovs_client.get('/alba/backends/{0}'.format(metadata['backend_info']['linked_guid']),
                                              params={'contents': 'presets'})
                presets = [preset for preset in backend_info['presets'] if preset['name'] == preset_name]
                if len(presets) != 1:
                    raise RuntimeError('Could not locate preset {0}'.format(preset_name))
                if presets[0]['is_available'] is False:
                    raise RuntimeError('Preset {0} is not available'.format(preset_name))
                AlbaController._logger.debug(backend_info)
                task_id = ovs_client.get('/alba/backends/{0}/get_config_metadata'.format(metadata['backend_info']['linked_guid']))
                successful, arakoon_config = ovs_client.wait_for_task(task_id, timeout=300)
                if successful is False:
                    raise RuntimeError('Could not load metadata from environment {0}'.format(ovs_client.ip))

                # Write Arakoon configuration to file
                arakoon_config = ArakoonClusterConfig.convert_config_to(config=arakoon_config, return_type='INI')
                remote_arakoon_config = '/opt/OpenvStorage/arakoon_config_temp'
                with open(remote_arakoon_config, 'w') as arakoon_cfg:
                    arakoon_cfg.write(arakoon_config)

                try:
                    AlbaCLI.run(command='add-osd',
                                config=config,
                                named_params={'prefix': alba_backend_guid,
                                              'preset': preset_name,
                                              'node-id': metadata['backend_info']['linked_guid'],
                                              'alba-osd-config-url': 'file://{0}'.format(remote_arakoon_config)})
                except AlbaError as ae:
                    if ae.error_code == 7 and ae.exception_type == AlbaError.ALBAMGR_EXCEPTION:
                        AlbaController._logger.warning('OSD with ID {0} has already been added'.format(linked_alba_id))
                        unclaimed_osds.append(linked_alba_id)
                        continue
                    AlbaController._logger.exception('Error adding OSD {0}'.format(linked_alba_id))
                    failure_osds.append(linked_alba_id)
                    continue
                finally:
                    os.remove(remote_arakoon_config)
            if is_claimed is False:
                try:
                    AlbaCLI.run(command='claim-osd', config=config, named_params={'long-id': linked_alba_id})
                except AlbaError as ae:
                    if ae.error_code == 11 and ae.exception_type == AlbaError.ALBAMGR_EXCEPTION:
                        AlbaController._logger.warning('OSD with ID {0} has already been claimed'.format(linked_alba_id))
                        unclaimed_osds.append(linked_alba_id)
                        continue
                    AlbaController._logger.exception('Error claiming OSD {0}'.format(linked_alba_id))
                    failure_osds.append(linked_alba_id)
                    continue
            osd = None
            for _osd in alba_backend.osds:
                if _osd.osd_id == linked_alba_id:
                    osd = _osd
                    break
            if osd is None:
                osd = AlbaOSD()
                osd.domain = domain
                osd.osd_id = linked_alba_id
                osd.osd_type = AlbaOSD.OSD_TYPES.ALBA_BACKEND
                osd.metadata = metadata
                osd.alba_backend = alba_backend
                osd.save()
        alba_backend.invalidate_dynamics()
        alba_backend.backend.invalidate_dynamics()
        return failure_osds, unclaimed_osds

    @staticmethod
    def _add_generic_osds(alba_backend_guid, alba_node_guid, osds, domain, metadata):
        """
        Adds and claims an OSD to the Backend
        :param alba_backend_guid: Guid of the ALBA Backend
        :type alba_backend_guid: str
        :param alba_node_guid: Guid of the ALBA Node
        :type alba_node_guid: str
        :param osds: OSDs to add to and claim on the ALBA Backend
        :type osds: list[dict]
        :param domain: domain
        :type domain: ovs.dal.hybrids.domain.Domain
        :param metadata: Metadata to add to the OSD (connection information for remote Backend, general Backend information)
        :type metadata: dict
        :raises AlbaError: - When ALBA cannot be polled for currently claimed and available OSDs
        :raises ValueError: - When duplicate port is specified in list of OSDs to add and / or claim
        :return: All OSDs if retrieving ALBA information fails or duplicate OSDs are specified and an empty list
                 or an empty list if retrieving ALBA information succeeds and a list of OSDs which could not be claimed
        :rtype: tuple
        """
        # Make mapping port <-> ips for each IP:port combination for all OSDs specified
        ip_port_osd_info_map = {}
        used_ip_ports = []

        for osd in AlbaOSDList.get_albaosds():
            if osd.osd_type != AlbaOSD.OSD_TYPES.ALBA_BACKEND:  # Only iterate over non-backend osds
                for ip in osd.ips:
                    used_ip_ports.append('{0}:{1}'.format(ip, osd.port))

        for requested_osd_info in osds:
            # Update osd_info with some additional information
            requested_osd_info['osd_id'] = None
            requested_osd_info['claimed'] = False
            requested_osd_info['available'] = False
            requested_osd_info['all_ip_ports'] = ['{0}:{1}'.format(ip, requested_osd_info['port']) for ip in requested_osd_info['ips']]

            # Dict keys 'ips', 'port' have been verified by public method 'add_osds' at this point
            for ip_port in requested_osd_info['all_ip_ports']:
                if ip_port in ip_port_osd_info_map or ip_port in used_ip_ports:
                    raise ValueError('Duplicate IP:port combination requested when trying to add and / or claim OSDs: {0}'.format(ip_port))
                ip_port_osd_info_map[ip_port] = requested_osd_info

        # Verify ALBA responsive to make mapping
        alba_backend = AlbaBackend(alba_backend_guid)
        config = Configuration.get_configuration_path(key=alba_backend.abm_cluster.config_location)
        try:
            claimed_osds = AlbaCLI.run(command='list-osds', config=config)
            available_osds = AlbaCLI.run(command='list-available-osds', config=config)
        except AlbaError:
            AlbaController._logger.exception('Could not load OSD information.')
            raise

        failure_osds = []
        unclaimed_osds = []
        # Verify each OSD whether it's already been claimed or just available for claiming
        for osd_list, osd_status in [[claimed_osds, 'claimed'],
                                     [available_osds, 'available']]:
            for actual_osd_info in osd_list:
                ips = actual_osd_info['ips']
                port = actual_osd_info['port']
                decommissioned = actual_osd_info['decommissioned']
                if decommissioned is True:  # Not suited for mapping
                    continue
                if ips is None:
                    # IPs can be None for OSDs of type Backend which have been added at this point, but not yet claimed
                    continue
                for ip in ips:
                    ip_port = '{0}:{1}'.format(ip, port)
                    if ip_port in ip_port_osd_info_map:
                        requested_osd_info = ip_port_osd_info_map[ip_port]
                        # Potential candidate, check ips
                        any_ip_match = not set(ips).isdisjoint(requested_osd_info['ips'])
                        if any_ip_match is False:
                            continue
                        requested_osd_info['osd_id'] = actual_osd_info['long_id']
                        requested_osd_info[osd_status] = True
                        break

        alba_node = AlbaNode(alba_node_guid)
        handled_ip_ports = []
        for ip_port, requested_osd_info in ip_port_osd_info_map.iteritems():
            if ip_port in handled_ip_ports:
                # The IP port osd info map contains all IP:port combinations for a single OSD. Since we cannot add, nor claim a single OSD multiple times,
                # we check here if a related IP port combination for the same OSD has already been handled.
                # Eg: OSD info contains IPs: ['10.100.1.1', '10.100.1.2'] and port 8600, then ip_port_osd_info_map will have 2 keys for this OSD: '10.100.1.1:8600' and '10.100.1.2:8600'
                continue
            handled_ip_ports.extend(requested_osd_info['all_ip_ports'])
            ips = requested_osd_info['ips']
            port = requested_osd_info['port']
            osd_id = requested_osd_info['osd_id']
            is_claimed = requested_osd_info['claimed']
            is_available = requested_osd_info['available']

            if is_claimed is False and is_available is False:
                register_ip = ips[0]
                try:
                    result = AlbaCLI.run(config=config,
                                         command='add-osd',
                                         named_params={'host': register_ip,
                                                       'port': port,
                                                       'node-id': alba_node.node_id})
                    osd_id = result['long_id']
                except AlbaError as ae:
                    if ae.error_code == 7 and ae.exception_type == AlbaError.ALBAMGR_EXCEPTION:
                        AlbaController._logger.warning('OSD {0}:{1} has already been added'.format(register_ip, port))
                        unclaimed_osds.append(osd_id)
                        continue
                    AlbaController._logger.exception('Error adding OSD on IP:port {0}:{1}'.format(register_ip, port))
                    failure_osds.append('{0}:{1}'.format(register_ip, port))
                    continue

                # TODO: Remove 'update-osd' once https://github.com/openvstorage/alba/issues/773 has been resolved, because we're supposed to register with all IPs right away
                if len(ips) > 1:
                    try:
                        AlbaCLI.run(config=config,
                                    command='update-osd',
                                    named_params={'long-id': osd_id,
                                                  'ip': ','.join(ips)})  # update-osd needs IPs as comma separated list
                    except AlbaError:
                        AlbaController._logger.exception('Error Updating OSD on IP:port {0}:{1} with IPs {2}'.format(register_ip, port, ', '.join(ips)))
                        failure_osds.append('{0}:{1}'.format(register_ip, port))
                        continue

            if is_claimed is False:
                try:
                    AlbaCLI.run(command='claim-osd', config=config, named_params={'long-id': osd_id})
                except AlbaError as ae:
                    if ae.error_code == 11 and ae.exception_type == AlbaError.ALBAMGR_EXCEPTION:
                        AlbaController._logger.warning('OSD with ID {0} has already been claimed'.format(osd_id))
                        unclaimed_osds.append(osd_id)
                        continue
                    AlbaController._logger.exception('Error claiming OSD with ID {0}'.format(osd_id))
                    failure_osds.append(port)
                    continue

            osd = AlbaOSD()
            for known_osd in alba_backend.osds:
                if known_osd.osd_id == osd_id:
                    osd = known_osd  # If it already exists, we'll now update it
                    break
            osd.ips = ips
            osd.port = port
            osd.osd_id = osd_id
            osd.domain = domain
            osd.slot_id = requested_osd_info['slot_id']
            osd.osd_type = getattr(AlbaOSD.OSD_TYPES, requested_osd_info['osd_type'])
            osd.metadata = metadata
            osd.alba_node = alba_node
            osd.alba_backend = alba_backend
            osd.save()

        alba_node.invalidate_dynamics()
        alba_backend.invalidate_dynamics()
        alba_backend.backend.invalidate_dynamics()
        # Dual Controller logic changes nothing about the claim. Only the stack should be updated
        if alba_node.alba_node_cluster is not None:
            alba_node.alba_node_cluster.invalidate_dynamics()
        return failure_osds, unclaimed_osds

    @staticmethod
    @ovs_task(name='alba.remove_units')
    def remove_units(alba_backend_guid, osd_ids):
        """
        Removes storage units from an ALBA Backend
        :param alba_backend_guid: Guid of the ALBA Backend
        :type alba_backend_guid: str
        :param osd_ids: IDs of the ASDs
        :type osd_ids: list
        :return: None
        """
        alba_backend = AlbaBackend(alba_backend_guid)
        if alba_backend.abm_cluster is None:
            raise ValueError('ALBA Backend {0} does not have an ABM cluster registered'.format(alba_backend.name))

        config = Configuration.get_configuration_path(key=alba_backend.abm_cluster.config_location)
        failed_osds = []
        last_exception = None
        for osd_id in osd_ids:
            try:
                AlbaCLI.run(command='purge-osd', config=config, named_params={'long-id': osd_id})
            except Exception as ex:
                if 'Albamgr_protocol.Protocol.Error.Osd_unknown' not in ex.message:
                    AlbaController._logger.exception('Error purging OSD {0}'.format(osd_id))
                    last_exception = ex
                    failed_osds.append(osd_id)
        if len(failed_osds) > 0:
            if len(osd_ids) == 1:
                raise last_exception
            raise RuntimeError('Error processing one or more OSDs: {0}'.format(failed_osds))

    @staticmethod
    @ovs_task(name='alba.add_cluster')
    def add_cluster(alba_backend_guid, abm_cluster=None, nsm_clusters=None):
        """
        Adds an Arakoon cluster to service Backend
        :param alba_backend_guid: Guid of the ALBA Backend
        :type alba_backend_guid: str
        :param abm_cluster: ABM cluster to use for this ALBA Backend
        :type abm_cluster: str
        :param nsm_clusters: NSM clusters to use for this ALBA Backend
        :type nsm_clusters: list[str]
        :return: None
        :rtype: NoneType
        """
        from ovs.lib.albanode import AlbaNodeController
        alba_backend = AlbaBackend(alba_backend_guid)

        if nsm_clusters is None:
            nsm_clusters = []
        try:
            counter = 0
            while counter < 300:
                if AlbaArakoonController.manual_alba_arakoon_checkup(alba_backend_guid=alba_backend_guid,
                                                                     abm_cluster=abm_cluster,
                                                                     nsm_clusters=nsm_clusters) is True:
                    break
                counter += 1
                time.sleep(1)
                if counter == 300:
                    raise RuntimeError('Arakoon checkup for ALBA Backend {0} could not be started'.format(alba_backend.name))
        except Exception as ex:
            AlbaController._logger.exception('Failed manual ALBA Arakoon checkup during add cluster for Backend {0}. {1}'.format(alba_backend_guid, ex))
            AlbaController.remove_cluster(alba_backend_guid=alba_backend_guid)
            raise

        config = Configuration.get_configuration_path(key=alba_backend.abm_cluster.config_location)
        alba_backend.alba_id = AlbaCLI.run(command='get-alba-id', config=config, named_params={'attempts': 5})['id']
        alba_backend.save()
        if not Configuration.exists(AlbaController.CONFIG_DEFAULT_NSM_HOSTS_KEY):
            Configuration.set(AlbaController.CONFIG_DEFAULT_NSM_HOSTS_KEY, 1)
        nsms = max(1, Configuration.get(AlbaController.CONFIG_DEFAULT_NSM_HOSTS_KEY))
        try:
            AlbaArakoonController.nsm_checkup(alba_backend_guid=alba_backend.guid, min_internal_nsms=nsms)
        except Exception as ex:
            AlbaController._logger.exception('Failed NSM checkup during add cluster for Backend {0}. {1}'.format(alba_backend.guid, ex))
            AlbaController.remove_cluster(alba_backend_guid=alba_backend.guid)
            raise

        # Enable cache eviction and auto-cleanup
        AlbaController.set_cache_eviction(alba_backend_guid, config=config)
        AlbaController.set_auto_cleanup(alba_backend_guid, config=config)

        # Mark the Backend as 'running'
        alba_backend.backend.status = Backend.STATUSES.RUNNING
        alba_backend.backend.save()

        AlbaNodeController.model_albanodes()
        AlbaController.checkup_maintenance_agents.delay()
        alba_backend.invalidate_dynamics('live_status')

    @staticmethod
    def can_set_auto_cleanup():
        # type: () -> bool
        """
        Return if it is possible to set the auto-cleanup
        :return: True if possible else False
        :rtype: bool
        """
        storagerouter = StorageRouterList.get_storagerouters()[0]
        return StorageRouter.ALBA_FEATURES.AUTO_CLEANUP in storagerouter.features['alba']['features']

    @staticmethod
    def set_auto_cleanup(alba_backend_guid, days=30, config=None):
        # type: (str, int) -> None
        """
        Set the auto cleanup policy for an ALBA Backend
        :param alba_backend_guid: Guid of the ALBA Backend to set the auto cleanup for
        :type alba_backend_guid: str
        :param days: Number of days to wait before cleaning up. Setting to 0 means disabling the auto cleanup
        and always clean up a namespace after removing it
        :type days: int
        :param config: Arakoon configuration of the backend (optional, for caching)
        :type config: str
        :return: None
        :rtype: NoneType
        """
        if not isinstance(days, int) or 0 > days:
            raise ValueError('Number of days must be an integer > 0')
        if AlbaController.can_set_auto_cleanup():
            if config is None:
                alba_backend = AlbaBackend(alba_backend_guid)
                config = Configuration.get_configuration_path(key=alba_backend.abm_cluster.config_location)
            # Check if the maintenance config was not set (disabled)
            maintenance_config = AlbaController.get_maintenance_config(alba_backend_guid, config)
            # Should be None when disabled (default behaviour)
            auto_cleanup_setting = maintenance_config.get('auto_cleanup_deleted_namespaces', None)
            if auto_cleanup_setting is not None and auto_cleanup_setting == days:
                return  # Nothing to do
            # Default to 30 days
            named_params = {'enable-auto-cleanup-deleted-namespaces-days': days}
            AlbaCLI.run(command='update-maintenance-config', config=config, named_params=named_params)

    @staticmethod
    def get_maintenance_config(alba_backend_guid, config=None):
        # type: (str, str) -> dict
        """
        Retrieve the maintenance config for an ALBA Backend
        :param alba_backend_guid: Guid of the ALBA Backend to extract the maintenance config from
        :type alba_backend_guid: str
        :param config: Arakoon configuration of the backend (optional, for caching)
        :type config: str
        :return: Maintenance config
        :rtype: dict
        """
        if config is None:
            alba_backend = AlbaBackend(alba_backend_guid)
            config = Configuration.get_configuration_path(key=alba_backend.abm_cluster.config_location)
        return AlbaCLI.run(command='get-maintenance-config', config=config)

    @staticmethod
    def set_cache_eviction(alba_backend_guid, config=None):
        # type: (str, str) -> None
        """
        Set the cache eviction for maintenance of an ALBA Backend
        :param alba_backend_guid: Guid of the ALBA Backend to set the cache eviction for
        :type alba_backend_guid: str
        :param config: Arakoon configuration of the backend (optional, for caching)
        :type config: str
        :return: None
        :rtype: NoneType
        """
        if config is None:
            alba_backend = AlbaBackend(alba_backend_guid)
            config = Configuration.get_configuration_path(key=alba_backend.abm_cluster.config_location)
        maintenance_config = AlbaController.get_maintenance_config(alba_backend_guid, config)
        eviction_types = maintenance_config.get('eviction_type', ['Automatic'])  # Defaults to ['Automatic'] normally
        # Check if update would be required. Put in place so Migration can call this function also
        if 'Automatic' in eviction_types:
            AlbaCLI.run(command='update-maintenance-config', config=config, extra_params=['--eviction-type-random'])

    @staticmethod
    def nodes_reachable():
        """
        Check if all AlbaNodes are reachable for a backend
        :return: None
        :rtype: NoneType
        :raises: RuntimeError: When an ABM could not be reached
        """
        for alba_node in AlbaNodeList.get_albanodes():
            try:
                alba_node.client.get_metadata()
            except requests.exceptions.ConnectionError as ce:
                raise RuntimeError('Node {0} is not reachable, ALBA Backend cannot be removed. {1}'.format(alba_node.ip, ce))

    @classmethod
    def remove_maintenance_services(cls, alba_backend, validate_nodes_reachable=True):
        # type: (AlbaBackend, bool) -> None
        """
        Remove all maintenance services for a backend
        :param alba_backend: AlbaBackend object
        :type alba_backend: AlbaBackend
        :param validate_nodes_reachable: Validate if all nodes are reachable first
        :type validate_nodes_reachable: bool
        :return: None
        :rtype: NoneType
        """
        if validate_nodes_reachable:
            cls.nodes_reachable()
        for node in AlbaNodeList.get_albanodes():
            node.invalidate_dynamics('maintenance_services')
            for service_info in node.maintenance_services.get(alba_backend.name, []):
                try:
                    node.client.remove_maintenance_service(name=service_info[0], alba_backend_guid=alba_backend.guid)
                    AlbaController._logger.info('Removed maintenance service {0} on {1}'.format(service_info[0], node.ip))
                except Exception:
                    AlbaController._logger.exception('Could not clean up maintenance services for {0}'.format(alba_backend.name))

    @staticmethod
    @ovs_task(name='alba.remove_cluster')
    def remove_cluster(alba_backend_guid):
        """
        Removes an ALBA Backend/cluster
        :param alba_backend_guid: Guid of the ALBA Backend
        :type alba_backend_guid: str
        :return: None
        """
        # VALIDATIONS
        alba_backend = AlbaBackend(alba_backend_guid)
        if len(alba_backend.osds) > 0:
            raise RuntimeError('An ALBA Backend with claimed OSDs cannot be removed')

        AlbaArakoonController.abms_reachable(alba_backend)
        AlbaArakoonController.nsms_reachable(alba_backend)
        AlbaController.nodes_reachable()

        # Removal
        alba_backend.backend.status = Backend.STATUSES.DELETING
        alba_backend.invalidate_dynamics('live_status')
        alba_backend.backend.save()
        # Remove all related Arakoons
        AlbaArakoonController.remove_alba_arakoon_clusters(alba_backend_guid, validate_clusters_reachable=False)

        # Delete maintenance agents
        AlbaController.remove_maintenance_services(alba_backend, False)

        config_key = AlbaController.CONFIG_ALBA_BACKEND_KEY.format(alba_backend_guid)
        AlbaController._logger.debug('Deleting ALBA Backend entry {0} from configuration management'.format(config_key))
        Configuration.delete(config_key)

        AlbaController._logger.debug('Deleting ALBA Backend from model')
        backend = alba_backend.backend
        for junction in list(backend.domains):
            junction.delete()
        alba_backend.delete()
        backend.delete()

    @staticmethod
    @ovs_task(name='alba.get_arakoon_config')
    def get_arakoon_config(alba_backend_guid):
        """
        Gets the Arakoon configuration for an ALBA Backend
        :param alba_backend_guid: Guid of the ALBA Backend
        :type alba_backend_guid: str
        :return: Arakoon cluster configuration information
        :rtype: dict
        """
        alba_backend = AlbaBackend(alba_backend_guid)
        if alba_backend.abm_cluster is None:
            raise ValueError('ALBA Backend {0} does not have an ABM cluster registered'.format(alba_backend.name))

        client = None
        service = None
        for abm_service in alba_backend.abm_cluster.abm_services:
            service = abm_service.service
            if service.is_internal is True:
                try:
                    client = SSHClient(service.storagerouter.ip)
                    break
                except UnableToConnectException:
                    pass
        if service is None or (client is None and service.is_internal is True):
            raise RuntimeError('Could not load Arakoon configuration')

        config = ArakoonClusterConfig(cluster_id=alba_backend.abm_cluster.name)
        return config.export_dict()

    @staticmethod
    def _link_plugins(client, data_dir, plugins, cluster_name):
        """
        Create symlinks for the Arakoon plugins to the correct (mounted) partition
        :param client: SSHClient to execute this on
        :type client: SSHClient
        :param data_dir: Directory on which the DB partition resides
        :type data_dir: str
        :param plugins: Plugins to symlink
        :type plugins: list
        :param cluster_name: Name of the Arakoon cluster
        :type cluster_name: str
        :return: None
        :rtype: NoneType
        """
        data_dir = '' if data_dir == '/' else data_dir
        for plugin in plugins:
            client.run(['ln', '-s', '{0}/{1}.cmxs'.format(AlbaController.ARAKOON_PLUGIN_DIR, plugin), ArakoonInstaller.ARAKOON_HOME_DIR.format(data_dir, cluster_name)])

    @staticmethod
    @add_hooks('nodetype', 'demote')
    def _on_demote(cluster_ip, master_ip, offline_node_ips=None):
        """
        A node is being demoted
        :param cluster_ip: IP of the cluster node to execute this on
        :type cluster_ip: str
        :param master_ip: IP of the master of the cluster
        :type master_ip: str
        :param offline_node_ips: IPs of nodes which are offline
        :type offline_node_ips: list
        :return: None
        """
        _ = master_ip
        if offline_node_ips is None:
            offline_node_ips = []

        for alba_backend in AlbaBackendList.get_albabackends():
            if alba_backend.abm_cluster is None:
                raise ValueError('ALBA Backend {0} does not have an ABM cluster registered'.format(alba_backend.name))

            internal = alba_backend.abm_cluster.abm_services[0].service.is_internal
            abm_cluster_name = alba_backend.abm_cluster.name
            if internal is True:
                # Remove the node from the ABM
                AlbaController._logger.info('Shrinking ABM for Backend {0}'.format(alba_backend.name))
                abm_storagerouter_ips = [abm_service.service.storagerouter.ip for abm_service in alba_backend.abm_cluster.abm_services]
                abm_remaining_ips = list(set(abm_storagerouter_ips).difference(set(offline_node_ips)))
                if len(abm_remaining_ips) == 0:
                    raise RuntimeError('No other available nodes found in the ABM cluster')

                if cluster_ip in abm_storagerouter_ips:
                    AlbaController._logger.info('* Shrink ABM cluster')
                    arakoon_installer = ArakoonInstaller(cluster_name=abm_cluster_name)
                    arakoon_installer.load()
                    arakoon_installer.shrink_cluster(removal_ip=cluster_ip,
                                                     offline_nodes=offline_node_ips)
                    arakoon_installer.restart_cluster_after_shrinking()

                    AlbaController._logger.info('* Updating ABM client config')
                    AlbaArakoonController._update_abm_client_config(abm_name=abm_cluster_name,
                                                                    ip=abm_remaining_ips[0])

                    AlbaController._logger.info('* Remove old ABM node from model')
                    abm_service = [abm_service for abm_service in alba_backend.abm_cluster.abm_services if abm_service.service.storagerouter.ip == cluster_ip][0]
                    abm_service.delete()
                    abm_service.service.delete()

                AlbaController._logger.info('Shrinking NSM for Backend {0}'.format(alba_backend.name))
                for nsm_cluster in alba_backend.nsm_clusters:
                    nsm_service_ips = [nsm_service.service.storagerouter.ip for nsm_service in nsm_cluster.nsm_services]
                    if cluster_ip not in nsm_service_ips:
                        # No need to shrink when NSM cluster was not extended over current node
                        continue

                    nsm_service_ips.remove(cluster_ip)
                    nsm_remaining_ips = list(set(nsm_service_ips).difference(set(offline_node_ips)))
                    if len(nsm_remaining_ips) == 0:
                        raise RuntimeError('No other available nodes found in the NSM cluster')

                    # Remove the node from the NSM
                    AlbaController._logger.info('* Shrink NSM cluster {0}'.format(nsm_cluster.name))
                    arakoon_installer = ArakoonInstaller(cluster_name=nsm_cluster.name)
                    arakoon_installer.shrink_cluster(removal_ip=cluster_ip,
                                                     offline_nodes=offline_node_ips)
                    arakoon_installer.restart_cluster_after_shrinking()

                    AlbaController._logger.info('* Updating NSM cluster config to ABM for cluster {0}'.format(nsm_cluster.name))
                    AlbaArakoonController._update_nsm(abm_name=abm_cluster_name,
                                                      nsm_name=nsm_cluster.name,
                                                      ip=nsm_remaining_ips[0])

                    AlbaController._logger.info('* Remove old NSM node from model')
                    nsm_service = [nsm_service for nsm_service in nsm_cluster.nsm_services if nsm_service.service.storagerouter.ip == cluster_ip][0]
                    nsm_service.delete()
                    nsm_service.service.delete()

    @staticmethod
    @add_hooks('noderemoval', 'remove')
    def _on_remove(cluster_ip, complete_removal):
        """
        A node is removed
        :param cluster_ip: IP of the node being removed
        :type cluster_ip: str
        :param complete_removal: Completely remove the ASDs and ASD-manager or only unlink
        :type complete_removal: bool
        :return: None
        """
        for alba_backend in AlbaBackendList.get_albabackends():
            for abm_service in alba_backend.abm_cluster.abm_services:
                if abm_service.service.is_internal is True and abm_service.service.storagerouter.ip == cluster_ip:
                    abm_service.delete()
                    abm_service.service.delete()
                    break
            for nsm_cluster in alba_backend.nsm_clusters:
                for nsm_service in nsm_cluster.nsm_services:
                    if nsm_service.service.is_internal is True and nsm_service.service.storagerouter.ip == cluster_ip:
                        nsm_service.delete()
                        nsm_service.service.delete()
                        break

        storage_router = StorageRouterList.get_by_ip(cluster_ip)
        if storage_router is None:
            AlbaController._logger.warning('Failed to retrieve StorageRouter with IP {0} from model'.format(cluster_ip))
            return

        if storage_router.alba_node is not None:
            alba_node = storage_router.alba_node
            if complete_removal is True:
                from ovs.lib.albanode import AlbaNodeController
                AlbaNodeController.remove_node(node_guid=storage_router.alba_node.guid)
            else:
                alba_node.storagerouter = None
                alba_node.save()

        for service in storage_router.services:
            service.delete()

    @staticmethod
    @add_hooks('noderemoval', 'validate_removal')
    def _validate_removal(cluster_ip):
        """
        Validate whether the specified StorageRouter can be removed
        :param cluster_ip: IP of the StorageRouter to validate for removal
        :type cluster_ip: str
        :return: None
        """
        for alba_backend in AlbaBackendList.get_albabackends():
            if alba_backend.abm_cluster is None:
                raise ValueError('ALBA Backend {0} does not have an ABM cluster registered'.format(alba_backend.name))
            if len(alba_backend.abm_cluster.abm_services) == 0:
                raise ValueError('ALBA Backend {0} does not have any registered ABM services'.format(alba_backend.name))

            if alba_backend.abm_cluster.abm_services[0].service.is_internal is False:
                continue

            abm_service_ips = [abm_service.service.storagerouter.ip for abm_service in alba_backend.abm_cluster.abm_services]
            if cluster_ip in abm_service_ips and len(abm_service_ips) == 1:
                raise RuntimeError('Node to remove is only node left in the ABM cluster for ALBA Backend {0}'.format(alba_backend.name))

            for nsm_cluster in alba_backend.nsm_clusters:
                nsm_service_ips = [nsm_service.service.storagerouter.ip for nsm_service in nsm_cluster.nsm_services]
                if cluster_ip in nsm_service_ips and len(nsm_service_ips) == 1:
                    raise RuntimeError('Node to remove is only node left in NSM cluster {0} for ALBA Backend {1}'.format(nsm_cluster.number, alba_backend.name))

    @staticmethod
    @add_hooks('noderemoval', 'validate_asd_removal')
    def _validate_asd_removal(storage_router_ip):
        """
        Do some validations before removing a node
        :param storage_router_ip: IP of the node trying to be removed
        :type storage_router_ip: str
        :return: Information about ASD safety
        :rtype: dict
        """
        storage_router = StorageRouterList.get_by_ip(storage_router_ip)
        if storage_router is None:
            raise RuntimeError('Failed to retrieve the StorageRouter with IP {0}'.format(storage_router_ip))

        osd_ids = {}
        if storage_router.alba_node is None:
            return {'confirm': False}

        for slot_info in storage_router.alba_node.stack.itervalues():
            for osd_id, osd_info in slot_info['osds'].iteritems():
                ab_guid = osd_info['claimed_by']
                if ab_guid is not None:
                    if ab_guid not in osd_ids:
                        osd_ids[ab_guid] = []
                    osd_ids[ab_guid].append(osd_id)

        confirm = False
        messages = []
        for alba_backend_guid, osd_ids in osd_ids.iteritems():
            alba_backend = AlbaBackend(alba_backend_guid)
            safety = AlbaController.calculate_safety(alba_backend_guid=alba_backend_guid, removal_osd_ids=osd_ids)
            if safety['lost'] > 0:
                confirm = True
                messages.append('The removal of this StorageRouter will cause data loss on Backend {0}'.format(alba_backend.name))
            elif safety['critical'] > 0:
                confirm = True
                messages.append('The removal of this StorageRouter brings data at risk on Backend {0}. Loosing more disks will cause data loss.'.format(alba_backend.name))
        return {'confirm': confirm,
                'question': '\n'.join(sorted(messages)) + '\nAre you sure you want to continue?'}

    @staticmethod
    @ovs_task(name='alba.calculate_safety')
    def calculate_safety(alba_backend_guid, removal_osd_ids):
        """
        Calculates/loads the safety when a certain set of disks are removed
        :param alba_backend_guid: Guid of the ALBA Backend
        :type alba_backend_guid: str
        :param removal_osd_ids: ASDs to take into account for safety calculation
        :type removal_osd_ids: list
        :return: Amount of good, critical and lost ASDs
        :rtype: dict
        """
        alba_backend = AlbaBackend(alba_backend_guid)
        if alba_backend.abm_cluster is None:
            raise ValueError('ALBA Backend {0} does not have an ABM cluster registered'.format(alba_backend.name))

        error_disks = []
        for slots in alba_backend.local_stack.values():
            for slot_information in slots.values():
                for osd_id, osd_info in slot_information['osds'].iteritems():
                    if osd_info['status'] == 'error':
                        error_disks.append(osd_id)
        extra_parameters = ['--include-decommissioning-as-dead']
        for osd in alba_backend.osds:
            if osd.osd_id in removal_osd_ids or osd.osd_id in error_disks:
                extra_parameters.append('--long-id={0}'.format(osd.osd_id))
        safety_data = []
        while True:
            try:
                config = Configuration.get_configuration_path(key=alba_backend.abm_cluster.config_location)
                safety_data = AlbaCLI.run(command='get-disk-safety', config=config, extra_params=extra_parameters)
                break
            except Exception as ex:
                if len(extra_parameters) > 1 and 'unknown osd' in ex.message:
                    match = re.search('osd ([^ "]*)', ex.message)
                    if match is not None:
                        osd_id = match.groups()[0]
                        AlbaController._logger.debug('Getting safety: skipping OSD {0}'.format(osd_id))
                        extra_parameters.remove('--long-id={0}'.format(osd_id))
                        continue
                raise
        result = {'good': 0,
                  'critical': 0,
                  'lost': 0}
        for namespace in safety_data:
            safety = namespace.get('safety')
            if safety is None or safety > 0:
                result['good'] += 1
            elif safety == 0:
                result['critical'] += 1
            else:
                result['lost'] += 1
        return result

    @staticmethod
    def get_load(nsm_cluster):
        """
        Calculates the load of an NSM node, returning a float percentage
        :param nsm_cluster: NSM cluster to retrieve the load for
        :type nsm_cluster: ovs.dal.hybrids.albansmcluster.NSMCluster
        :return: Load of the NSM service
        :rtype: float
        """
        service_capacity = float(nsm_cluster.capacity)
        if service_capacity < 0:
            return 50.0
        if service_capacity == 0:
            return float('inf')

        config = Configuration.get_configuration_path(key=nsm_cluster.alba_backend.abm_cluster.config_location)
        hosts_data = AlbaCLI.run(command='list-nsm-hosts', config=config)
        host = [host for host in hosts_data if host['id'] == nsm_cluster.name][0]
        usage = host['namespaces_count']
        return round(usage / service_capacity * 100.0, 5)

    @staticmethod
    @add_hooks('nodeinstallation', ['firstnode', 'extranode'])  # Arguments: cluster_ip and for extra node also master_ip
    @add_hooks('plugin', ['postinstall'])  # Arguments: ip
    def _add_base_configuration(*args, **kwargs):
        _ = args, kwargs
        key = '/ovs/framework/plugins/alba/config'
        if not Configuration.exists(key):
            Configuration.set(key, {'nsm': {'maxload': 75,
                                            'safety': 3}})
        key = '/ovs/framework/plugins/installed'
        installed = Configuration.get(key)
        if 'alba' not in installed['backends']:
            installed['backends'].append('alba')
            Configuration.set(key, installed)
        key = '/ovs/alba/backends/global_gui_error_interval'
        if not Configuration.exists(key):
            Configuration.set(key, 300)
        key = '/ovs/framework/hosts/{0}/versions|alba'
        for storagerouter in StorageRouterList.get_storagerouters():
            machine_id = storagerouter.machine_id
            if not Configuration.exists(key.format(machine_id)):
                Configuration.set(key.format(machine_id), ExtensionMigrator.THIS_VERSION)

    @staticmethod
    @ovs_task(name='alba.link_alba_backends')
    def link_alba_backends(alba_backend_guid, metadata):
        """
        Link a GLOBAL ALBA Backend to a LOCAL or another GLOBAL ALBA Backend
        :param alba_backend_guid: ALBA Backend guid to link another ALBA Backend to
        :type alba_backend_guid: str
        :param metadata: Metadata about the linked ALBA Backend
        :type metadata: dict
        :return: Returns True if the linking of the ALBA Backends went successfully or
                 False if the ALBA Backend to link is in 'decommissioned' state
        :rtype: bool
        """
        ExtensionsToolbox.verify_required_params(required_params={'backend_connection_info': (dict, {'host': (str, ExtensionsToolbox.regex_ip),
                                                                                                     'port': (int, {'min': 1, 'max': 65535}),
                                                                                                     'username': (str, None),
                                                                                                     'password': (str, None)}),
                                                                  'backend_info': (dict, {'domain_guid': (str, ExtensionsToolbox.regex_guid, False),
                                                                                          'linked_guid': (str, ExtensionsToolbox.regex_guid),
                                                                                          'linked_name': (str, ExtensionsToolbox.regex_vpool),
                                                                                          'linked_preset': (str, ExtensionsToolbox.regex_preset),
                                                                                          'linked_alba_id': (str, ExtensionsToolbox.regex_guid)})},
                                                 actual_params=metadata)

        linked_alba_id = metadata['backend_info']['linked_alba_id']
        try:
            AlbaController.add_osds(alba_backend_guid=alba_backend_guid,
                                    osds=[{'osd_type': AlbaOSD.OSD_TYPES.ALBA_BACKEND, 'osd_id': linked_alba_id}],
                                    metadata=metadata)
        except DecommissionedException:
            return False
        AlbaController.checkup_maintenance_agents.delay()
        return True

    @staticmethod
    @ovs_task(name='alba.unlink_alba_backends')
    def unlink_alba_backends(target_guid, linked_guid):
        """
        Unlink a LOCAL or GLOBAL ALBA Backend from a GLOBAL ALBA Backend
        :param target_guid: Guid of the GLOBAL ALBA Backend from which a link will be removed
        :type target_guid: str
        :param linked_guid: Guid of the GLOBAL or LOCAL ALBA Backend which will be unlinked (Can be a local or a remote ALBA Backend)
        :type linked_guid: str
        :return: None
        """
        parent = AlbaBackend(target_guid)
        linked_osd = None
        for osd in parent.osds:
            if osd.metadata is not None and osd.metadata['backend_info']['linked_guid'] == linked_guid:
                linked_osd = osd
                break

        if linked_osd is not None:
            AlbaController.remove_units(alba_backend_guid=parent.guid, osd_ids=[linked_osd.osd_id])
            linked_osd.delete()
        parent.invalidate_dynamics()
        parent.backend.invalidate_dynamics()
        AlbaController.checkup_maintenance_agents.delay()

    @staticmethod
    def get_read_preferences_for_global_backend(alba_backend, alba_node_id, read_preferences):
        """
        Retrieve the read preferences for a GLOBAL ALBA Backend and ALBA Node combination
        WARNING: Max recursion depth exceeded error possible, because when for example:
            Global1 is linked to global2, which is linked to global3, which is linked to global1
        :param alba_backend: ALBA Backend for which the read preferences are retrieved
        :type alba_backend: ovs.dal.hybrids.albabackend.AlbaBackend
        :param alba_node_id: Node ID for the ALBA Node to which the ALBA Backend is related
        :type alba_node_id: str
        :param read_preferences: List of read preferences found (Should be empty list for initial caller)
        :type read_preferences: list
        :return: The read preferences found for the combination of ALBA Backend and ALBA Node (See checkup_maintenance_agents for explanation)
        :rtype: list
        """
        for osd in alba_backend.osds:
            if osd.osd_type == AlbaOSD.OSD_TYPES.ALBA_BACKEND:
                if osd.metadata is not None:
                    try:
                        linked_alba_backend = AlbaBackend(osd.metadata['backend_info']['linked_guid'])
                    except ObjectNotFoundException:
                        # Object not found, because the linked ALBA Backend will be a remote 1. Since we don't want to configure this as a 'read_preference' ... continue
                        continue
                    # noinspection PyTypeChecker
                    AlbaController.get_read_preferences_for_global_backend(alba_backend=linked_alba_backend,
                                                                           alba_node_id=alba_node_id,
                                                                           read_preferences=read_preferences)
            elif osd.alba_node.node_id == alba_node_id:  # Current ALBA Backend has ASDs, so add current ALBA Backend GUID as read_preference for the calling ALBA Backend
                read_preferences.append(alba_backend.alba_id)
                break
        return list(set(read_preferences))

    @staticmethod
    @ovs_task(name='alba.checkup_maintenance_agents', schedule=Schedule(minute='0', hour='*'), ensure_single_info={'mode': 'CHAINED'})
    def checkup_maintenance_agents(alba_backend_guid=None):
        """
        Check if requested nr of maintenance agents per ALBA Backend is actually present
        Add / remove maintenance agents to fulfill the requested layout or the requested amount of services (configurable through configuration management)
        Some prerequisites:
            * At least 1 maintenance agent is deployed regardless of amount of linked OSDs (ASDs / Backends / ADs)
            * Max 1 maintenance agent per ALBA Backend per ALBA Node
            * For ALBA Backends with scaling LOCAL:
                * Configured read preference will be the node on which the maintenance agent is being deployed
            * For ALBA Backends with scaling GLOBAL:
                * Configured read preference can never be a linked remote ALBA Backend (scaling LOCAL nor GLOBAL)
                * Priority for deploying maintenance agents goes to ALBA Nodes which provide a read preference, see example below
                * 'global1'  -->  'local1'    (Has ASDs on ALBA Node 1, ALBA Node 2)
                *            -->  'local2'    (Has ASDs on ALBA Node 1)
                *            -->  'global2'
                * 'global2'  -->  'local3'    (Has ASDs on ALBA Node 1, ALBA Node 3)
                *            -->  'remote1'
                * 'global3'  -->  'local2'
                *            -->  'remote1'
                * In above scenario:
                    * Maintenance agent on ALBA Node 1 for 'global1' --> read preferences are: [ALBA ID of 'local1', ALBA ID of 'local2', ALBA ID of 'local3']
                    * Maintenance agent on ALBA Node 2 for 'global1' --> read preferences are: [ALBA ID of 'local1']
                    * Maintenance agent on ALBA Node 3 for 'global1' --> read preferences are: [ALBA ID of 'local3']

                    * Maintenance agent on ALBA Node 1 for 'global2' --> read preferences are: [ALBA ID of 'local3']
                    * Maintenance agent on ALBA Node 2 for 'global2' --> read preferences are: []
                    * Maintenance agent on ALBA Node 3 for 'global2' --> read preferences are: [ALBA ID of 'local3']

                    * Maintenance agent on ALBA Node 1 for 'global3' --> read preferences are: [ALBA ID of 'local1']
                    * Maintenance agent on ALBA Node 2 for 'global3' --> read preferences are: []
                    * Maintenance agent on ALBA Node 3 for 'global3' --> read preferences are: []

                    * In case required amount of maintenance agents is 2 (Priority to ALBA Nodes which provide the most read preferences)
                        * For 'global1', Maintenance agents on nodes 1 and (2 or 3)
                        * For 'global2', Maintenance agents on nodes 1 and 3
                        * For 'global3', Maintenance agents on nodes 1 and (2 or 3)
        :param alba_backend_guid: GUID of the ALBA Backend for which the maintenance agents need to be checked
        :type alba_backend_guid: str
        :raises Exception: If anything fails adding/removing maintenance agents for any ALBA Backend
        :return: None
        :rtype: NoneType
        """

        def add_service(_alba_backend, _alba_node, _reason):
            # noinspection PyTypeChecker
            unique_hash = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(16))
            _service_name = 'alba-maintenance_{0}-{1}'.format(_alba_backend.name, unique_hash)

            AlbaController._logger.info('Adding service {0} on ALBA Node {1} - Reason: {2}'.format(_service_name, _alba_node.ip, _reason))
            if _alba_backend.scaling == AlbaBackend.SCALINGS.LOCAL:
                _read_preferences = [_alba_node.node_id]
            else:
                try:
                    _read_preferences = AlbaController.get_read_preferences_for_global_backend(alba_backend=_alba_backend,
                                                                                               alba_node_id=_alba_node.node_id,
                                                                                               read_preferences=[])
                except:
                    _read_preferences = []

            try:
                _alba_node.client.add_maintenance_service(name=_service_name,
                                                          alba_backend_guid=_alba_backend.guid,
                                                          abm_name=_alba_backend.abm_cluster.name,
                                                          read_preferences=_read_preferences)
                AlbaController._logger.debug('Added service {0} on ALBA Node {1}'.format(_service_name, _alba_node.ip))
                return True
            except Exception:
                AlbaController._logger.exception('Adding service {0} on ALBA Node {1} failed'.format(_service_name, _alba_node.ip))
            return False

        def remove_service(_alba_backend, _alba_node, _service_name, _reason):
            AlbaController._logger.info('Removing service {0} from ALBA Node {1} - Reason: {2}'.format(_service_name, _alba_node.ip, _reason))
            try:
                _alba_node.client.remove_maintenance_service(name=_service_name, alba_backend_guid=_alba_backend.guid)
                AlbaController._logger.debug('Removed service {0} from ALBA Node {1}'.format(_service_name, _alba_node.ip))
                return True
            except Exception:
                AlbaController._logger.exception('Removing service {0} from ALBA Node {1} failed'.format(_service_name, _alba_node.ip))
            return False

        def get_allowed_nodes_per_backend():
            """
            Retrieve per ALBA Backend, the ALBA Nodes on which each ALBA Backend has ASDs claimed
            """
            for _alba_node in services_per_node:
                if _alba_node.type == AlbaNode.NODE_TYPES.GENERIC:
                    continue
                for slot_info in _alba_node.stack.itervalues():
                    for osd_info in slot_info['osds'].itervalues():
                        ab_guid = osd_info['claimed_by']
                        if ab_guid is not None:
                            try:
                                ab = AlbaBackend(ab_guid)
                                if ab not in allowed_nodes_per_backend:
                                    allowed_nodes_per_backend[ab] = set()
                                allowed_nodes_per_backend[ab].add(_alba_node)
                            except ObjectNotFoundException:
                                pass
            for ab in allowed_nodes_per_backend:
                sorted(allowed_nodes_per_backend[ab], key=lambda _node: load_per_node[_node])
            return allowed_nodes_per_backend

        AlbaController._logger.info('Loading maintenance information')
        alba_nodes = sorted(AlbaNodeList.get_albanodes_by_type(AlbaNode.NODE_TYPES.ASD),
                            key=lambda an: ExtensionsToolbox.advanced_sort(element=an.ip, separator='.'))
        success_add = True
        alba_backends = [AlbaBackend(alba_backend_guid)] if alba_backend_guid is not None else sorted(AlbaBackendList.get_albabackends(), key=lambda ab: ExtensionsToolbox.advanced_sort(element=ab.name, separator='.'))
        load_per_node = {}
        success_remove = True
        services_per_node = {}
        alba_backend_name_map = dict((alba_backend.name, alba_backend) for alba_backend in alba_backends)
        allowed_nodes_per_backend = {}

        # Retrieve load per ALBA Node, services per ALBA Node
        for alba_node in alba_nodes:
            AlbaController._logger.debug('ALBA Node {0} - Node ID {1}'.format(alba_node.ip, alba_node.node_id))
            try:
                alba_node.client.get_metadata()
            except requests.ConnectionError:
                AlbaController._logger.error('ASD Manager is not available on ALBA Node {0} with ID {1}'.format(alba_node.ip, alba_node.node_id))
                continue

            if alba_node not in load_per_node:
                load_per_node[alba_node] = 0
            if alba_node not in services_per_node:
                services_per_node[alba_node] = {}

            alba_node.invalidate_dynamics('maintenance_services')
            for alba_backend_name, all_services in alba_node.maintenance_services.iteritems():
                if len(all_services) == 0:
                    continue

                for index, service_info in enumerate(all_services):
                    load_per_node[alba_node] += 1
                    if index > 0 and alba_backend_name in alba_backend_name_map:
                        # noinspection PyTypeChecker
                        removed = remove_service(_alba_backend=alba_backend_name_map[alba_backend_name],
                                                 _alba_node=alba_node,
                                                 _service_name=service_info[0],
                                                 _reason='Multiple services for ALBA Backend on ALBA Node')
                        success_remove &= removed
                        if removed is True:
                            load_per_node[alba_node] -= 1
                services_per_node[alba_node][alba_backend_name] = all_services[0][0]

        # Log current deployment
        for alba_node in sorted(services_per_node, key=lambda an: ExtensionsToolbox.advanced_sort(element=an.ip, separator='.')):
            for alba_backend_name in sorted(services_per_node[alba_node]):
                AlbaController._logger.debug('ALBA Node {0} - ALBA Backend {1} - Service {2}'.format(alba_node.ip, alba_backend_name, services_per_node[alba_node][alba_backend_name]))

        # Do the calculation for each ALBA Backend
        for alba_backend in alba_backends:
            AlbaController._logger.info('Processing ALBA Backend {0} - Scaling {1} - ALBA ID {2}'.format(alba_backend.name, alba_backend.scaling, alba_backend.alba_id))
            if alba_backend.abm_cluster is None:
                AlbaController._logger.warning('ALBA Backend {0} does not have an ABM cluster registered'.format(alba_backend.name))
                continue

            # Verify requested layout
            layout = None
            layout_config_key = AlbaController.AGENTS_LAYOUT_CONFIG_KEY.format(alba_backend.guid)
            if Configuration.exists(layout_config_key):
                layout = Configuration.get(layout_config_key)
                AlbaController._logger.debug('Requested layout: {0}'.format(layout))
                if not isinstance(layout, list):
                    layout = None
                    AlbaController._logger.warning('Layout is not a list and will be ignored')
                else:
                    layout = set(layout)
                    alba_node_ids = set(node.node_id for node in services_per_node)
                    if len(layout) == len(layout - alba_node_ids):
                        AlbaController._logger.warning('Layout does not contain any known/reachable nodes and will be ignored')
                        layout = None
                    else:
                        for entry in layout - alba_node_ids:
                            AlbaController._logger.warning('Layout contains unknown/unreachable node {0}'.format(entry))
                        layout = layout.intersection(alba_node_ids)

            #############
            # WITH LAYOUT
            services_to_add = []
            services_to_remove = []
            services_for_backend = 0
            if layout is not None:
                AlbaController._logger.debug('Applying layout: {0}'.format(layout))
                services_for_backend = len(layout)
                # Make sure every requested ALBA Node gets 1 service
                for alba_node_id in layout:
                    alba_node = AlbaNodeList.get_albanode_by_node_id(node_id=alba_node_id)
                    AlbaController._logger.debug('Verifying ALBA Node {0} with ID {1}'.format(alba_node.ip, alba_node.node_id))
                    if alba_backend.name not in services_per_node[alba_node]:  # No services for current ALBA Backend on requested ALBA Node
                        services_to_add.append([alba_node, 'Requested by layout'])
                        load_per_node[alba_node] += 1
                    else:  # Current ALBA Node has a service as requested
                        AlbaController._logger.debug('Keeping service {0} on ALBA Node {1}'.format(services_per_node[alba_node][alba_backend.name], alba_node.ip))
                        services_per_node[alba_node].pop(alba_backend.name)

                # Remove any previously deployed services, which have not been requested
                for alba_node, alba_backend_info in services_per_node.iteritems():
                    if alba_backend.name in alba_backend_info:
                        service_name = alba_backend_info[alba_backend.name]
                        services_to_remove.append([alba_node, service_name, 'Not requested by layout'])
                        load_per_node[alba_node] -= 1

            ################
            # WITHOUT LAYOUT
            else:
                # Verify amount of requested services
                nr_of_agents_config_key = AlbaController.NR_OF_AGENTS_CONFIG_KEY.format(alba_backend.guid)
                if Configuration.exists(key=nr_of_agents_config_key):
                    requested_services = Configuration.get(key=nr_of_agents_config_key)
                else:
                    requested_services = 3
                    Configuration.set(key=nr_of_agents_config_key, value=3)

                AlbaController._logger.debug('Requested amount of services: {0}'.format(requested_services))
                if alba_backend.scaling == AlbaBackend.SCALINGS.LOCAL:
                    if len(allowed_nodes_per_backend) == 0:  # Not initialized yet
                        allowed_nodes_per_backend = get_allowed_nodes_per_backend()

                    allowed_nodes_for_backend = allowed_nodes_per_backend.get(alba_backend, [])
                    AlbaController._logger.debug('Possible amount of services: {0}'.format(len(allowed_nodes_for_backend)))
                    for allowed_node in allowed_nodes_for_backend:
                        AlbaController._logger.debug('Allowed ALBA Node {0} with ID {1}'.format(allowed_node.ip, allowed_node.node_id))

                    # Remove wrongly placed services, obsolete services and multiple services on ALBA Nodes
                    for alba_node, alba_backend_info in services_per_node.iteritems():
                        if alba_backend.name not in alba_backend_info:
                            # Current ALBA Backend does not have services deployed on 'alba_node'
                            continue

                        if services_for_backend == requested_services:
                            # We have enough services found for this ALBA Backend
                            services_to_remove.append([alba_node, alba_backend_info.pop(alba_backend.name), 'Too many services'])
                            load_per_node[alba_node] -= 1
                        elif alba_backend in allowed_nodes_per_backend:
                            if alba_node not in allowed_nodes_per_backend[alba_backend]:
                                # Current ALBA Node has a service for current ALBA Backend, but is not an allowed ALBA Node
                                services_to_remove.append([alba_node, alba_backend_info.pop(alba_backend.name), 'Service found on non-allowed ALBA Node'])
                                load_per_node[alba_node] -= 1
                            else:
                                # Current ALBA Node has a service for current ALBA Backend (Duplicate services have already been removed at this point)
                                AlbaController._logger.debug('Keeping service {0} on ALBA Node {1}'.format(alba_backend_info[alba_backend.name], alba_node.ip))
                                allowed_nodes_per_backend[alba_backend].remove(alba_node)
                                services_for_backend += 1
                        else:  # No allowed ALBA Nodes for current ALBA Backend, so we only need 1 service
                            if services_for_backend == 1:
                                services_to_remove.append([alba_node, alba_backend_info.pop(alba_backend.name), 'Service found on non-allowed ALBA Node'])
                                load_per_node[alba_node] -= 1
                            else:
                                AlbaController._logger.debug('Keeping service {0} on non-allowed ALBA Node {1} because no other allowed ALBA Nodes are available'.format(alba_backend_info[alba_backend.name], alba_node.ip))
                                services_for_backend = 1

                    # Make sure the requested amount is reached or until we run out of allowed ALBA Nodes
                    for alba_node in allowed_nodes_per_backend.get(alba_backend, []):
                        if services_for_backend == requested_services:
                            break
                        services_to_add.append([alba_node, 'Not enough services'])
                        load_per_node[alba_node] += 1
                        services_for_backend += 1

                elif alba_backend.scaling == AlbaBackend.SCALINGS.GLOBAL:  # 'elif' stack for readability, could be 'else' stack
                    # Verify how many read_preferences current ALBA Backend would have on each ALBA Node
                    preference_node_map = {}
                    for alba_node in services_per_node:
                        new_read_preferences = []
                        try:
                            # noinspection PyTypeChecker
                            new_read_preferences = AlbaController.get_read_preferences_for_global_backend(alba_backend=alba_backend,
                                                                                                          alba_node_id=alba_node.node_id,
                                                                                                          read_preferences=[])
                        except:
                            AlbaController._logger.exception('Failed to retrieve the read preferences for ALBA Backend {0} on ALBA Node {1}'.format(alba_backend.name, alba_node.node_id))

                        amount_preferences = len(new_read_preferences)
                        if amount_preferences not in preference_node_map:
                            preference_node_map[amount_preferences] = []

                        if alba_backend.name in services_per_node[alba_node]:
                            config_key = AlbaController.CONFIG_ALBA_BACKEND_KEY.format('{0}/maintenance/{1}/config'.format(alba_backend.guid, services_per_node[alba_node][alba_backend.name]))
                            try:
                                old_read_preferences = sorted(Configuration.get(key=config_key)['read_preference'])
                            except (KeyError, NotFoundException):
                                old_read_preferences = []
                                AlbaController._logger.exception('Failed to retrieve currently configured read preferences on ALBA Node {0} with ID {1}'.format(alba_node.ip, alba_node.node_id))
                            preference_node_map[amount_preferences].insert(0, [alba_node, old_read_preferences, new_read_preferences])  # Priority to ALBA Nodes which already have a service deployed
                        else:
                            preference_node_map[amount_preferences].append([alba_node, [], new_read_preferences])
                        AlbaController._logger.debug('ALBA Node {0} with ID {1} has {2} read preference{3}'.format(alba_node.ip, alba_node.node_id, amount_preferences, '' if amount_preferences == 1 else 's'))

                    # Add (or keep) services on ALBA Nodes with the most read preferences
                    linked_backends = sum(alba_backend.local_summary['devices'].values())
                    AlbaController._logger.debug('Amount of linked ALBA Backends: {0}'.format(linked_backends))
                    for pref_amount in sorted(preference_node_map, reverse=True):  # We prefer ALBA nodes with more read preferences
                        # Break if requested amount has been reached or if no Backends have been linked we only want to deploy 1 maintenance agent
                        if services_for_backend == requested_services or (services_for_backend == 1 and linked_backends == 0):
                            break

                        AlbaController._logger.debug('Verifying ALBA Nodes with {0} read preference{1}'.format(pref_amount, '' if pref_amount == 1 else 's'))
                        for alba_node, old_preferences, new_preferences in preference_node_map[pref_amount]:
                            AlbaController._logger.debug('Verifying ALBA Node {0} with ID {1}'.format(alba_node.ip, alba_node.node_id))
                            if services_for_backend == requested_services or (services_for_backend == 1 and linked_backends == 0):
                                break
                            if alba_node in services_per_node and alba_backend.name in services_per_node[alba_node]:
                                service_name = services_per_node[alba_node][alba_backend.name]
                                if old_preferences == new_preferences:
                                    AlbaController._logger.debug('Keeping service {0} on ALBA Node {1}'.format(service_name, alba_node.ip))
                                    services_per_node[alba_node].pop(alba_backend.name)
                                else:
                                    AlbaController._logger.debug('Removing and re-adding service due to change in preferences: {0} <--> {1}'.format(', '.join(old_preferences), ', '.join(new_preferences)))
                                    services_to_add.append([alba_node, 'Change in read preferences'])
                                    services_to_remove.append([alba_node, service_name, 'Change in read preferences'])
                                services_for_backend += 1
                            elif alba_node in services_per_node:
                                AlbaController._logger.error('Alba Node in services per node')
                                services_to_add.append([alba_node, 'Most read preferences ({0})'.format(pref_amount)])
                                load_per_node[alba_node] += 1
                                services_for_backend += 1

                    # Remove all services on ALBA Nodes which have not been checked because requested amount has been reached
                    for alba_node, alba_backend_info in services_per_node.iteritems():
                        if alba_backend.name in alba_backend_info:
                            services_to_remove.append([alba_node, alba_backend_info[alba_backend.name], 'Too many services'])
                            load_per_node[alba_node] -= 1

            # Always make sure to have at least 1 service for each ALBA Backend, even if it has no OSDs yet
            if services_for_backend == 0:
                min_load = min(load_per_node.values()) if load_per_node else 0
                AlbaController._logger.debug('No services yet for ALBA Backend {0}. Minimum load is {1}'.format(alba_backend.name, min_load))
                for alba_node, load in load_per_node.iteritems():
                    if load == min_load:
                        services_to_add.append([alba_node, 'Minimal load detected'])
                        load_per_node[alba_node] += 1
                        break

            if services_to_remove:
                AlbaController._logger.info('Removing {0} service{1}'.format(len(services_to_remove), '' if len(services_to_remove) == 1 else 's'))
            for alba_node, service_name, reason in services_to_remove:
                # noinspection PyTypeChecker
                success_remove &= remove_service(_alba_backend=alba_backend, _alba_node=alba_node, _service_name=service_name, _reason=reason)

            if services_to_add:
                AlbaController._logger.info('Adding {0} service{1}'.format(len(services_to_add), '' if len(services_to_add) == 1 else 's'))
            for alba_node, reason in services_to_add:
                # noinspection PyTypeChecker
                success_add &= add_service(_alba_backend=alba_backend, _alba_node=alba_node, _reason=reason)
            if len(services_to_remove) > 0 or len(services_to_add) > 0:
                alba_backend.invalidate_dynamics('live_status')
                alba_backend.backend.invalidate_dynamics('live_status')

        if success_add is False or success_remove is False:
            raise Exception('Maintenance agent checkup was not completely successful')

    @staticmethod
    @ovs_task(name='alba.verify_namespaces', schedule=Schedule(minute='0', hour='0', day_of_month='1', month_of_year='*/3'))
    def verify_namespaces():
        """
        Verify namespaces for all backends
        """
        AlbaController._logger.info('Verify namespace task scheduling started')

        verification_factor = Configuration.get('/ovs/alba/backends/verification_factor', default=10)
        for alba_backend in AlbaBackendList.get_albabackends():
            if alba_backend.abm_cluster is None:
                raise ValueError('ALBA Backend {0} does not have an ABM cluster registered'.format(alba_backend.name))

            config = Configuration.get_configuration_path(key=alba_backend.abm_cluster.config_location)
            namespaces = AlbaCLI.run(command='list-namespaces', config=config)
            for namespace in namespaces:
                ns_name = namespace['name']
                AlbaController._logger.info('Scheduled namespace {0} for verification'.format(ns_name))
                AlbaCLI.run(command='verify-namespace',
                            config=config,
                            named_params={'factor': verification_factor},
                            extra_params=[ns_name, '{0}_{1}'.format(alba_backend.name, ns_name)])

        AlbaController._logger.info('Verify namespace task scheduling finished')

    @staticmethod
    @add_hooks('backend', 'domains-update')
    def _post_backend_domains_updated(backend_guid):
        """
        Execute this functionality when the Backend Domains have been updated
        :param backend_guid: Guid of the Backend to be updated
        :type backend_guid: str
        :return: None
        """
        backend = Backend(backend_guid)
        backend.alba_backend.invalidate_dynamics('local_summary')
