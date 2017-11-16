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
import datetime
import requests
import collections
from ovs.dal.exceptions import ObjectNotFoundException
from ovs.dal.hybrids.albaabmcluster import ABMCluster
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.hybrids.albansmcluster import NSMCluster
from ovs.dal.hybrids.albaosd import AlbaOSD
from ovs.dal.hybrids.backend import Backend
from ovs.dal.hybrids.diskpartition import DiskPartition
from ovs.dal.hybrids.domain import Domain
from ovs.dal.hybrids.j_abmservice import ABMService
from ovs.dal.hybrids.j_nsmservice import NSMService
from ovs.dal.hybrids.service import Service as DalService
from ovs.dal.hybrids.servicetype import ServiceType
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs.dal.lists.albaosdlist import AlbaOSDList
from ovs.dal.lists.servicetypelist import ServiceTypeList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs_extensions.api.client import OVSClient
from ovs.extensions.db.arakooninstaller import ArakoonClusterConfig, ArakoonInstaller
from ovs.extensions.generic.configuration import Configuration, NotFoundException
from ovs.extensions.generic.logger import Logger
from ovs.extensions.generic.sshclient import SSHClient, UnableToConnectException
from ovs.extensions.packages.albapackagefactory import PackageFactory
from ovs.extensions.plugins.albacli import AlbaCLI, AlbaError
from ovs.extensions.storage.volatilefactory import VolatileFactory
from ovs.lib.helpers.decorators import add_hooks, ovs_task
from ovs.lib.helpers.toolbox import Schedule, Toolbox


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
        Currently used to update the IPs on which the OSD should be exposed
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
                Toolbox.verify_required_params(required_params={'ips': (list, Toolbox.regex_ip)},
                                               actual_params=osd_data)
            except RuntimeError as ex:
                validation_reasons.append(str(ex))
                continue

            osd = AlbaOSDList.get_by_osd_id(osd_id)
            if osd is None:
                validation_reasons.append('OSD with ID {0} has not yet been registered.'.format(osd_id))
                continue

            if osd_data['ips'] == osd.ips:
                AlbaController._logger.info('OSD with ID {0} already has the requested IPs configured: {1}'.format(osd_id, ', '.join(osd.ips)))
                continue
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
            ips = osd_data['ips']
            osd = osd_data['object']
            orig_ips = osd.ips
            config_location = Configuration.get_configuration_path(key=osd.alba_backend.abm_cluster.config_location)
            AlbaController._logger.debug('OSD with ID {0}: Updating on ALBA'.format(osd_id))
            try:
                alba_node.client.update_osd(slot_id=osd.slot_id,
                                            osd_id=osd.osd_id,
                                            update_data={'ips': ips})
            except Exception:
                AlbaController._logger.exception('OSD with ID {0}: Failed to update IPs via asd-manager'.format(osd_id))
                failures.append(osd_id)
                continue

            try:
                AlbaCLI.run(command='update-osd', config=config_location, named_params={'long-id': osd_id, 'ip': ','.join(ips)})
            except AlbaError:
                AlbaController._logger.exception('OSD with ID {0}: Failed to update IPs via ALBA'.format(osd_id))
                failures.append(osd_id)
                continue

            AlbaController._logger.debug('OSD with ID {0}: Updating in model'.format(osd_id))
            try:
                osd.ips = ips
                osd.save()
            except Exception:
                failures.append(osd_id)
                try:  # Updated in ALBA, so try to revert config in ALBA, because model is out of sync
                    AlbaCLI.run(command='update-osd', config=config_location, named_params={'long-id': osd_id, 'ip': ','.join(orig_ips)})
                except AlbaError:
                    AlbaController._logger.exception('OSD with ID {0}: Failed to revert OSD IPs from new IPs {1} to original IPs {2}'.format(osd_id, ', '.join(ips), ', '.join(orig_ips)))
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
        :param alba_node_guid: Guid of the ALBA Node
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
                    required.update({'ips': (list, Toolbox.regex_ip),
                                     'port': (int, {'min': 1, 'max': 65535}),
                                     'slot_id': (str, None)})
                Toolbox.verify_required_params(required_params=required, actual_params=osd)
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
                ovs_client = OVSClient(ip=connection_info['host'],
                                       port=connection_info['port'],
                                       credentials=(connection_info['username'], connection_info['password']),
                                       cache_store=VolatileFactory.get_client(),
                                       version=6)
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
        for requested_osd_info in osds:
            # Update osd_info with some additional information
            requested_osd_info['osd_id'] = None
            requested_osd_info['claimed'] = False
            requested_osd_info['available'] = False
            requested_osd_info['all_ip_ports'] = ['{0}:{1}'.format(ip, requested_osd_info['port']) for ip in requested_osd_info['ips']]

            # Dict keys 'ips', 'port' have been verified by public method 'add_osds' at this point
            for ip_port in requested_osd_info['all_ip_ports']:
                if ip_port in ip_port_osd_info_map:
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
                if decommissioned is True:
                    failure_osds.append('{0}:{1}'.format(ips[0], port))
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
                if AlbaController.manual_alba_arakoon_checkup(alba_backend_guid=alba_backend_guid,
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
            AlbaController.nsm_checkup(alba_backend_guid=alba_backend.guid, min_internal_nsms=nsms)
        except Exception as ex:
            AlbaController._logger.exception('Failed NSM checkup during add cluster for Backend {0}. {1}'.format(alba_backend.guid, ex))
            AlbaController.remove_cluster(alba_backend_guid=alba_backend.guid)
            raise

        # Enable LRU
        key = AlbaController.CONFIG_ALBA_BACKEND_KEY.format('lru_redis')
        if Configuration.exists(key, raw=True):
            endpoint = Configuration.get(key, raw=True).strip().strip('/')
        else:
            masters = StorageRouterList.get_masters()
            endpoint = 'redis://{0}:6379'.format(masters[0].ip)
        redis_endpoint = '{0}/alba_lru_{1}'.format(endpoint, alba_backend.guid)
        AlbaCLI.run(command='update-maintenance-config', config=config, named_params={'set-lru-cache-eviction': redis_endpoint})

        # Mark the Backend as 'running'
        alba_backend.backend.status = Backend.STATUSES.RUNNING
        alba_backend.backend.save()

        AlbaNodeController.model_albanodes()
        AlbaController.checkup_maintenance_agents.delay()
        alba_backend.invalidate_dynamics('live_status')

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

        if alba_backend.abm_cluster is not None:
            # Check ABM cluster reachable
            for abm_service in alba_backend.abm_cluster.abm_services:
                if abm_service.service.is_internal is True:
                    service = abm_service.service
                    try:
                        SSHClient(endpoint=service.storagerouter, username='root')
                    except UnableToConnectException:
                        raise RuntimeError('Node {0} with IP {1} is not reachable, ALBA Backend cannot be removed.'.format(service.storagerouter.name, service.storagerouter.ip))

            # Check all NSM clusters reachable
            for nsm_cluster in alba_backend.nsm_clusters:
                for nsm_service in nsm_cluster.nsm_services:
                    service = nsm_service.service
                    if service.is_internal is True:
                        try:
                            SSHClient(endpoint=service.storagerouter, username='root')
                        except UnableToConnectException:
                            raise RuntimeError('Node {0} with IP {1} is not reachable, ALBA Backend cannot be removed'.format(service.storagerouter.name, service.storagerouter.ip))

        # Check storage nodes reachable
        for alba_node in AlbaNodeList.get_albanodes():
            try:
                alba_node.client.list_maintenance_services()
            except requests.exceptions.ConnectionError as ce:
                raise RuntimeError('Node {0} is not reachable, ALBA Backend cannot be removed. {1}'.format(alba_node.ip, ce))

        # ACTUAL REMOVAL
        alba_backend.backend.status = Backend.STATUSES.DELETING
        alba_backend.invalidate_dynamics('live_status')
        alba_backend.backend.save()
        if alba_backend.abm_cluster is not None:
            AlbaController._logger.debug('Removing ALBA Backend {0}'.format(alba_backend.name))
            internal = alba_backend.abm_cluster.abm_services[0].service.is_internal
            abm_cluster_name = alba_backend.abm_cluster.name
            arakoon_clusters = list(Configuration.list('/ovs/arakoon'))
            if abm_cluster_name in arakoon_clusters:
                # Remove ABM Arakoon cluster
                arakoon_installer = ArakoonInstaller(cluster_name=abm_cluster_name)
                arakoon_installer.load()
                if internal is True:
                    AlbaController._logger.debug('Deleting ALBA manager Arakoon cluster {0}'.format(abm_cluster_name))
                    arakoon_installer.delete_cluster()
                    AlbaController._logger.debug('Deleted ALBA manager Arakoon cluster {0}'.format(abm_cluster_name))
                else:
                    AlbaController._logger.debug('Un-claiming ALBA manager Arakoon cluster {0}'.format(abm_cluster_name))
                    arakoon_installer.unclaim_cluster()
                    AlbaController._logger.debug('Unclaimed ALBA manager Arakoon cluster {0}'.format(abm_cluster_name))

            # Remove ABM Arakoon services
            for abm_service in alba_backend.abm_cluster.abm_services:
                abm_service.delete()
                abm_service.service.delete()
                if internal is True:
                    AlbaController._logger.debug('Removed service {0} on node {1}'.format(abm_service.service.name, abm_service.service.storagerouter.name))
                else:
                    AlbaController._logger.debug('Removed service {0}'.format(abm_service.service.name))
            alba_backend.abm_cluster.delete()

            # Remove NSM Arakoon clusters and services
            for nsm_cluster in alba_backend.nsm_clusters:
                if nsm_cluster.name in arakoon_clusters:
                    arakoon_installer = ArakoonInstaller(cluster_name=nsm_cluster.name)
                    arakoon_installer.load()
                    if internal is True:
                        AlbaController._logger.debug('Deleting Namespace manager Arakoon cluster {0}'.format(nsm_cluster.name))
                        arakoon_installer.delete_cluster()
                        AlbaController._logger.debug('Deleted Namespace manager Arakoon cluster {0}'.format(nsm_cluster.name))
                    else:
                        AlbaController._logger.debug('Un-claiming Namespace manager Arakoon cluster {0}'.format(nsm_cluster.name))
                        arakoon_installer.unclaim_cluster()
                        AlbaController._logger.debug('Unclaimed Namespace manager Arakoon cluster {0}'.format(nsm_cluster.name))
                for nsm_service in nsm_cluster.nsm_services:
                    nsm_service.delete()
                    nsm_service.service.delete()
                    AlbaController._logger.debug('Removed service {0}'.format(nsm_service.service.name))
                nsm_cluster.delete()

        # Delete maintenance agents
        for node in AlbaNodeList.get_albanodes():
            try:
                for service_name in node.client.list_maintenance_services():
                    backend_name = service_name.split('_', 1)[1].rsplit('-', 1)[0]  # E.g. alba-maintenance_my-backend-a4f7e3c61
                    if backend_name == alba_backend.name:
                        node.client.remove_maintenance_service(service_name)
                        AlbaController._logger.info('Removed maintenance service {0} on {1}'.format(service_name, node.ip))
            except Exception:
                AlbaController._logger.exception('Could not clean up maintenance services for {0}'.format(alba_backend.name))

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
    @ovs_task(name='alba.scheduled_alba_arakoon_checkup',
              schedule=Schedule(minute='30', hour='*'),
              ensure_single_info={'mode': 'DEFAULT', 'extra_task_names': ['alba.manual_alba_arakoon_checkup']})
    def scheduled_alba_arakoon_checkup():
        """
        Makes sure the volumedriver Arakoon is on all available master nodes
        :return: None
        """
        AlbaController._alba_arakoon_checkup()

    @staticmethod
    @ovs_task(name='alba.manual_alba_arakoon_checkup',
              ensure_single_info={'mode': 'DEFAULT', 'extra_task_names': ['alba.scheduled_alba_arakoon_checkup']})
    def manual_alba_arakoon_checkup(alba_backend_guid, nsm_clusters, abm_cluster=None):
        """
        Creates a new Arakoon cluster if required and extends cluster if possible on all available master nodes
        :param alba_backend_guid: Guid of the ALBA Backend
        :type alba_backend_guid: str
        :param nsm_clusters: NSM clusters for this ALBA Backend
        :type nsm_clusters: list[str]
        :param abm_cluster: ABM cluster for this ALBA Backend
        :type abm_cluster: str|None
        :return: True if task completed, None if task was discarded (by decorator)
        :rtype: bool|None
        """
        if (abm_cluster is not None and len(nsm_clusters) == 0) or (len(nsm_clusters) > 0 and abm_cluster is None):
            raise ValueError('Both ABM cluster and NSM clusters must be provided')
        if abm_cluster is not None:
            for cluster_name in [abm_cluster] + nsm_clusters:
                try:
                    metadata = ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=cluster_name)
                    if metadata['in_use'] is True:
                        raise ValueError('Cluster {0} has already been claimed'.format(cluster_name))
                except NotFoundException:
                    raise ValueError('Could not find an Arakoon cluster with name: {0}'.format(cluster_name))
        AlbaController._alba_arakoon_checkup(alba_backend_guid=alba_backend_guid,
                                             abm_cluster=abm_cluster,
                                             nsm_clusters=nsm_clusters)
        return True

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
    def _alba_arakoon_checkup(alba_backend_guid=None, abm_cluster=None, nsm_clusters=None):
        slaves = StorageRouterList.get_slaves()
        masters = StorageRouterList.get_masters()
        clients = {}
        available_storagerouters = {}
        for storagerouter in masters + slaves:
            try:
                clients[storagerouter] = SSHClient(storagerouter)
                if storagerouter in masters:
                    storagerouter.invalidate_dynamics(['partition_config'])
                    if len(storagerouter.partition_config[DiskPartition.ROLES.DB]) > 0:
                        available_storagerouters[storagerouter] = DiskPartition(storagerouter.partition_config[DiskPartition.ROLES.DB][0])
            except UnableToConnectException:
                AlbaController._logger.warning('Storage Router with IP {0} is not reachable'.format(storagerouter.ip))

        alba_pkg_name, alba_version_cmd = PackageFactory.get_package_and_version_cmd_for(component='alba')  # Call here, because this potentially raises error, which should happen before actually making changes
        version_str = '{0}=`{1}`'.format(alba_pkg_name, alba_version_cmd)

        # Cluster creation
        if alba_backend_guid is not None:
            alba_backend = AlbaBackend(alba_backend_guid)
            abm_cluster_name = '{0}-abm'.format(alba_backend.name)

            # ABM Arakoon cluster creation
            if alba_backend.abm_cluster is None:
                metadata = ArakoonInstaller.get_unused_arakoon_metadata_and_claim(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.ABM,
                                                                                  cluster_name=abm_cluster)
                if metadata is None:  # No externally unused clusters found, we create 1 ourselves
                    if not available_storagerouters:
                        raise RuntimeError('Could not find any partitions with DB role')
                    if abm_cluster is not None:
                        raise ValueError('Cluster {0} has been claimed by another process'.format(abm_cluster))
                    AlbaController._logger.info('Creating Arakoon cluster: {0}'.format(abm_cluster_name))
                    storagerouter, partition = available_storagerouters.items()[0]
                    arakoon_installer = ArakoonInstaller(cluster_name=abm_cluster_name)
                    arakoon_installer.create_cluster(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.ABM,
                                                     ip=storagerouter.ip,
                                                     base_dir=partition.folder,
                                                     plugins={AlbaController.ABM_PLUGIN: version_str})
                    AlbaController._link_plugins(client=clients[storagerouter],
                                                 data_dir=partition.folder,
                                                 plugins=[AlbaController.ABM_PLUGIN],
                                                 cluster_name=abm_cluster_name)
                    arakoon_installer.start_cluster()
                    ports = arakoon_installer.ports[storagerouter.ip]
                    metadata = arakoon_installer.metadata
                else:
                    ports = []
                    storagerouter = None

                abm_cluster_name = metadata['cluster_name']
                AlbaController._logger.info('Claimed {0} managed Arakoon cluster: {1}'.format('externally' if storagerouter is None else 'internally', abm_cluster_name))
                AlbaController._update_abm_client_config(abm_name=abm_cluster_name,
                                                         ip=clients.keys()[0].ip)
                AlbaController._model_service(alba_backend=alba_backend,
                                              cluster_name=abm_cluster_name,
                                              ports=ports,
                                              storagerouter=storagerouter)

            # NSM Arakoon cluster creation
            if len(alba_backend.nsm_clusters) == 0 and nsm_clusters is not None:
                ports = []
                storagerouter = None
                if len(nsm_clusters) > 0:
                    metadatas = []
                    for nsm_cluster in nsm_clusters:
                        metadata = ArakoonInstaller.get_unused_arakoon_metadata_and_claim(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM,
                                                                                          cluster_name=nsm_cluster)
                        if metadata is None:
                            AlbaController._logger.warning('Arakoon cluster {0} has been claimed by another process, reverting...'.format(nsm_cluster))
                            for md in metadatas:
                                ArakoonInstaller(cluster_name=md['cluster_name']).unclaim_cluster()
                            ArakoonInstaller(cluster_name=abm_cluster_name).unclaim_cluster()
                            raise ValueError('Arakoon cluster {0} has been claimed by another process'.format(nsm_cluster))
                        metadatas.append(metadata)
                else:
                    metadata = ArakoonInstaller.get_unused_arakoon_metadata_and_claim(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM)
                    if metadata is None:  # No externally unused clusters found, we create 1 ourselves
                        if not available_storagerouters:
                            raise RuntimeError('Could not find any partitions with DB role')

                        nsm_cluster_name = '{0}-nsm_0'.format(alba_backend.name)
                        AlbaController._logger.info('Creating Arakoon cluster: {0}'.format(nsm_cluster_name))
                        storagerouter, partition = available_storagerouters.items()[0]
                        arakoon_installer = ArakoonInstaller(cluster_name=nsm_cluster_name)
                        arakoon_installer.create_cluster(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM,
                                                         ip=storagerouter.ip,
                                                         base_dir=partition.folder,
                                                         plugins={AlbaController.NSM_PLUGIN: version_str})
                        AlbaController._link_plugins(client=clients[storagerouter],
                                                     data_dir=partition.folder,
                                                     plugins=[AlbaController.NSM_PLUGIN],
                                                     cluster_name=nsm_cluster_name)
                        arakoon_installer.start_cluster()
                        ports = arakoon_installer.ports[storagerouter.ip]
                        metadata = arakoon_installer.metadata
                    metadatas = [metadata]

                for index, metadata in enumerate(metadatas):
                    nsm_cluster_name = metadata['cluster_name']
                    AlbaController._logger.info('Claimed {0} managed Arakoon cluster: {1}'.format('externally' if storagerouter is None else 'internally', nsm_cluster_name))
                    AlbaController._register_nsm(abm_name=abm_cluster_name,
                                                 nsm_name=nsm_cluster_name,
                                                 ip=clients.keys()[0])
                    AlbaController._model_service(alba_backend=alba_backend,
                                                  cluster_name=nsm_cluster_name,
                                                  ports=ports,
                                                  storagerouter=storagerouter,
                                                  number=index)

        # ABM Cluster extension
        for alba_backend in AlbaBackendList.get_albabackends():
            if alba_backend.abm_cluster is None:
                AlbaController._logger.warning('ALBA Backend {0} does not have an ABM cluster registered'.format(alba_backend.name))
                continue

            abm_cluster_name = alba_backend.abm_cluster.name
            metadata = ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=abm_cluster_name)
            if 0 < len(alba_backend.abm_cluster.abm_services) < len(available_storagerouters) and metadata['internal'] is True:
                current_abm_ips = [abm_service.service.storagerouter.ip for abm_service in alba_backend.abm_cluster.abm_services]
                for storagerouter, partition in available_storagerouters.iteritems():
                    if storagerouter.ip in current_abm_ips:
                        continue
                    arakoon_installer = ArakoonInstaller(cluster_name=abm_cluster_name)
                    arakoon_installer.load()
                    arakoon_installer.extend_cluster(new_ip=storagerouter.ip,
                                                     base_dir=partition.folder,
                                                     plugins={AlbaController.ABM_PLUGIN: version_str})
                    AlbaController._link_plugins(client=clients[storagerouter],
                                                 data_dir=partition.folder,
                                                 plugins=[AlbaController.ABM_PLUGIN],
                                                 cluster_name=abm_cluster_name)
                    AlbaController._model_service(alba_backend=alba_backend,
                                                  cluster_name=abm_cluster_name,
                                                  ports=arakoon_installer.ports[storagerouter.ip],
                                                  storagerouter=storagerouter)
                    arakoon_installer.restart_cluster_after_extending(new_ip=storagerouter.ip)
                    AlbaController._update_abm_client_config(abm_name=abm_cluster_name,
                                                             ip=storagerouter.ip)
                    current_abm_ips.append(storagerouter.ip)

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
                    AlbaController._update_abm_client_config(abm_name=abm_cluster_name,
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
                    AlbaController._update_nsm(abm_name=abm_cluster_name,
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
    @ovs_task(name='alba.nsm_checkup', schedule=Schedule(minute='45', hour='*'), ensure_single_info={'mode': 'CHAINED'})
    def nsm_checkup(alba_backend_guid=None, min_internal_nsms=1, external_nsm_cluster_names=list()):
        """
        Validates the current NSM setup/configuration and takes actions where required.
        Assumptions:
        * A 2 node NSM is considered safer than a 1 node NSM.
        * When adding an NSM, the nodes with the least amount of NSM participation are preferred

        :param alba_backend_guid: Run for a specific ALBA Backend
        :type alba_backend_guid: str
        :param min_internal_nsms: Minimum amount of NSM hosts that need to be provided
        :type min_internal_nsms: int
        :param external_nsm_cluster_names: Information about the additional clusters to claim (only for externally managed Arakoon clusters)
        :type external_nsm_cluster_names: list
        :return: None
        :rtype: NoneType
        """
        ###############
        # Validations #
        ###############
        AlbaController._logger.info('NSM checkup started')
        if min_internal_nsms < 1:
            raise ValueError('Minimum amount of NSM clusters must be 1 or more')

        if not isinstance(external_nsm_cluster_names, list):
            raise ValueError("'external_nsm_cluster_names' must be of type 'list'")

        if len(external_nsm_cluster_names) > 0:
            if alba_backend_guid is None:
                raise ValueError('Additional NSMs can only be configured for a specific ALBA Backend')
            if min_internal_nsms > 1:
                raise ValueError("'min_internal_nsms' and 'external_nsm_cluster_names' are mutually exclusive")

            external_nsm_cluster_names = list(set(external_nsm_cluster_names))  # Remove duplicate cluster names
            for cluster_name in external_nsm_cluster_names:
                try:
                    ArakoonInstaller.get_arakoon_metadata_by_cluster_name(cluster_name=cluster_name)
                except NotFoundException:
                    raise ValueError('Arakoon cluster with name {0} does not exist'.format(cluster_name))

        if alba_backend_guid is None:
            alba_backends = [alba_backend for alba_backend in AlbaBackendList.get_albabackends() if alba_backend.backend.status == 'RUNNING']
        else:
            alba_backends = [AlbaBackend(alba_backend_guid)]

        masters = StorageRouterList.get_masters()
        storagerouters = set()
        for alba_backend in alba_backends:
            if alba_backend.abm_cluster is None:
                raise ValueError('No ABM cluster found for ALBA Backend {0}'.format(alba_backend.name))
            if len(alba_backend.abm_cluster.abm_services) == 0:
                raise ValueError('ALBA Backend {0} does not have any registered ABM services'.format(alba_backend.name))
            if len(alba_backend.nsm_clusters) + len(external_nsm_cluster_names) > 50:
                raise ValueError('The maximum of 50 NSM Arakoon clusters will be exceeded. Amount of clusters that can be deployed for this ALBA Backend: {0}'.format(50 - len(alba_backend.nsm_clusters)))
            # Validate enough externally managed Arakoon clusters are available
            if alba_backend.abm_cluster.abm_services[0].service.is_internal is False:
                unused_cluster_names = set([cluster_info['cluster_name'] for cluster_info in ArakoonInstaller.get_unused_arakoon_clusters(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM)])
                if set(external_nsm_cluster_names).difference(unused_cluster_names):
                    raise ValueError('Some of the provided cluster_names have already been claimed before')
                storagerouters.update(set(masters))  # For externally managed we need an available master node
            else:
                for abm_service in alba_backend.abm_cluster.abm_services:  # For internally managed we need all StorageRouters online
                    storagerouters.add(abm_service.service.storagerouter)
                for nsm_cluster in alba_backend.nsm_clusters:  # For internally managed we need all StorageRouters online
                    for nsm_service in nsm_cluster.nsm_services:
                        storagerouters.add(nsm_service.service.storagerouter)

        storagerouter_cache = {}
        for storagerouter in storagerouters:
            try:
                storagerouter_cache[storagerouter] = SSHClient(endpoint=storagerouter)
            except UnableToConnectException:
                raise RuntimeError('StorageRouter {0} with IP {1} is not reachable'.format(storagerouter.name, storagerouter.ip))

        alba_pkg_name, alba_version_cmd = PackageFactory.get_package_and_version_cmd_for(component='alba')  # Call here, because this potentially raises error, which should happen before actually making changes
        version_str = '{0}=`{1}`'.format(alba_pkg_name, alba_version_cmd)

        ##################
        # Check Clusters #
        ##################
        safety = Configuration.get('/ovs/framework/plugins/alba/config|nsm.safety')
        maxload = Configuration.get('/ovs/framework/plugins/alba/config|nsm.maxload')

        AlbaController._logger.debug('NSM safety is configured at: {0}'.format(safety))
        AlbaController._logger.debug('NSM max load is configured at: {0}'.format(maxload))

        master_client = None
        failed_backends = []
        for alba_backend in alba_backends:
            try:
                # Gather information
                AlbaController._logger.info('ALBA Backend {0} - Ensuring NSM safety'.format(alba_backend.name))

                internal = alba_backend.abm_cluster.abm_services[0].service.is_internal
                nsm_loads = collections.OrderedDict()
                nsm_storagerouters = {}
                sorted_nsm_clusters = sorted(alba_backend.nsm_clusters, key=lambda k: k.number)
                for nsm_cluster in sorted_nsm_clusters:
                    nsm_loads[nsm_cluster.number] = AlbaController.get_load(nsm_cluster)
                    if internal is True:
                        for nsm_service in nsm_cluster.nsm_services:
                            if nsm_service.service.storagerouter not in nsm_storagerouters:
                                nsm_storagerouters[nsm_service.service.storagerouter] = 0
                            nsm_storagerouters[nsm_service.service.storagerouter] += 1

                if internal is True:
                    for abm_service in alba_backend.abm_cluster.abm_services:
                        if abm_service.service.storagerouter not in nsm_storagerouters:
                            nsm_storagerouters[abm_service.service.storagerouter] = 0

                elif internal is False and len(external_nsm_cluster_names) > 0:
                    for sr, cl in storagerouter_cache.iteritems():
                        if sr.node_type == 'MASTER':
                            master_client = cl
                            break
                    if master_client is None:
                        # Internal is False and we specified the NSM clusters to claim, but no MASTER nodes online
                        raise ValueError('Could not find an online master node')

                AlbaController._logger.debug('ALBA Backend {0} - Arakoon clusters are {1} managed'.format(alba_backend.name, 'internally' if internal is True else 'externally'))
                for nsm_number, nsm_load in nsm_loads.iteritems():
                    AlbaController._logger.debug('ALBA Backend {0} - NSM Cluster {1} - Load {2}'.format(alba_backend.name, nsm_number, nsm_load))
                for sr, count in nsm_storagerouters.iteritems():
                    AlbaController._logger.debug('ALBA Backend {0} - StorageRouter {1} - NSM Services {2}'.format(alba_backend.name, sr.name, count))

                abm_cluster_name = alba_backend.abm_cluster.name
                if internal is True:
                    # Extend existing NSM clusters if safety not met
                    for nsm_cluster in sorted_nsm_clusters:
                        AlbaController._logger.debug('ALBA Backend {0} - Processing NSM {1} - Expected safety {2} - Current safety {3}'.format(alba_backend.name, nsm_cluster.number, safety, len(nsm_cluster.nsm_services)))
                        # Check amount of nodes
                        if len(nsm_cluster.nsm_services) < safety:
                            AlbaController._logger.info('ALBA Backend {0} - Extending if possible'.format(alba_backend.name))
                            current_sr_ips = [nsm_service.service.storagerouter.ip for nsm_service in nsm_cluster.nsm_services]
                            available_srs = [storagerouter for storagerouter in nsm_storagerouters if storagerouter.ip not in current_sr_ips]

                            # As long as there are available StorageRouters and safety not met
                            while len(available_srs) > 0 and len(current_sr_ips) < safety:
                                candidate_sr = None
                                candidate_load = None
                                for storagerouter in available_srs:
                                    if candidate_load is None:
                                        candidate_sr = storagerouter
                                        candidate_load = nsm_storagerouters[storagerouter]
                                    elif nsm_storagerouters[storagerouter] < candidate_load:
                                        candidate_sr = storagerouter
                                        candidate_load = nsm_storagerouters[storagerouter]
                                if candidate_sr is None or candidate_load is None:
                                    raise RuntimeError('Could not determine a candidate StorageRouter')
                                current_sr_ips.append(candidate_sr.ip)
                                available_srs.remove(candidate_sr)
                                # Extend the cluster (configuration, services, ...)
                                candidate_sr.invalidate_dynamics('partition_config')
                                partition = DiskPartition(candidate_sr.partition_config[DiskPartition.ROLES.DB][0])
                                arakoon_installer = ArakoonInstaller(cluster_name=nsm_cluster.name)
                                arakoon_installer.load()

                                AlbaController._logger.debug('ALBA Backend {0} - Extending cluster {1} on node {2} with IP {3}'.format(alba_backend.name, nsm_cluster.name, candidate_sr.name, candidate_sr.ip))
                                arakoon_installer.extend_cluster(new_ip=candidate_sr.ip,
                                                                 base_dir=partition.folder,
                                                                 plugins={AlbaController.NSM_PLUGIN: version_str})
                                AlbaController._logger.debug('ALBA Backend {0} - Linking plugins'.format(alba_backend.name))
                                AlbaController._link_plugins(client=storagerouter_cache[candidate_sr],
                                                             data_dir=partition.folder,
                                                             plugins=[AlbaController.NSM_PLUGIN],
                                                             cluster_name=nsm_cluster.name)
                                AlbaController._logger.debug('ALBA Backend {0} - Modeling services'.format(alba_backend.name))
                                AlbaController._model_service(alba_backend=alba_backend,
                                                              cluster_name=nsm_cluster.name,
                                                              ports=arakoon_installer.ports[candidate_sr.ip],
                                                              storagerouter=candidate_sr,
                                                              number=nsm_cluster.number)
                                AlbaController._logger.debug('ALBA Backend {0} - Restarting cluster'.format(alba_backend.name))
                                arakoon_installer.restart_cluster_after_extending(new_ip=candidate_sr.ip)
                                AlbaController._update_nsm(abm_name=abm_cluster_name,
                                                           nsm_name=nsm_cluster.name,
                                                           ip=candidate_sr.ip)
                                AlbaController._logger.debug('ALBA Backend {0} - Extended cluster'.format(alba_backend.name))

                overloaded = min(nsm_loads.values()) >= maxload
                if overloaded is False:  # At least 1 NSM is not overloaded yet
                    AlbaController._logger.debug('ALBA Backend {0} - NSM load OK'.format(alba_backend.name))
                    if internal is True:
                        nsms_to_add = max(0, min_internal_nsms - len(nsm_loads))  # When load is not OK, deploy at least 1 additional NSM
                    else:
                        nsms_to_add = len(external_nsm_cluster_names)
                    if nsms_to_add == 0:
                        continue
                else:
                    AlbaController._logger.warning('ALBA Backend {0} - NSM load is NOT OK'.format(alba_backend.name))
                    if internal is True:
                        nsms_to_add = max(1, min_internal_nsms - len(nsm_loads))  # When load is not OK, deploy at least 1 additional NSM
                    else:
                        nsms_to_add = len(external_nsm_cluster_names)  # For externally managed clusters we only claim the specified clusters, if none provided, we just log it
                        if nsms_to_add == 0:
                            AlbaController._logger.critical('ALBA Backend {0} - All NSM clusters are overloaded'.format(alba_backend.name))
                            continue

                # Deploy new (internal) or claim existing (external) NSM clusters
                AlbaController._logger.debug('ALBA Backend {0} - Currently {1} NSM cluster{2}'.format(alba_backend.name, len(nsm_loads), '' if len(nsm_loads) == 1 else 's'))
                AlbaController._logger.debug('ALBA Backend {0} - Trying to add {1} NSM cluster{2}'.format(alba_backend.name, nsms_to_add, '' if nsms_to_add == 1 else 's'))
                base_number = max(nsm_loads.keys()) + 1
                for index, number in enumerate(xrange(base_number, base_number + nsms_to_add)):
                    if internal is False:  # External clusters
                        nsm_cluster_name = external_nsm_cluster_names[index]
                        AlbaController._logger.debug('ALBA Backend {0} - Claiming NSM cluster {1}'.format(alba_backend.name, nsm_cluster_name))
                        metadata = ArakoonInstaller.get_unused_arakoon_metadata_and_claim(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM,
                                                                                          cluster_name=nsm_cluster_name)
                        if metadata is None:
                            AlbaController._logger.critical('ALBA Backend {0} - NSM cluster with name {1} could not be found'.format(alba_backend.name, nsm_cluster_name))
                            continue

                        AlbaController._logger.debug('ALBA Backend {0} - Modeling services'.format(alba_backend.name))
                        AlbaController._model_service(alba_backend=alba_backend,
                                                      cluster_name=nsm_cluster_name,
                                                      number=number)
                        AlbaController._logger.debug('ALBA Backend {0} - Registering NSM'.format(alba_backend.name))
                        AlbaController._register_nsm(abm_name=abm_cluster_name,
                                                     nsm_name=nsm_cluster_name,
                                                     ip=master_client.ip)
                        AlbaController._logger.debug('ALBA Backend {0} - Extended cluster'.format(alba_backend.name))
                    else:  # Internal clusters
                        nsm_cluster_name = '{0}-nsm_{1}'.format(alba_backend.name, number)
                        AlbaController._logger.debug('ALBA Backend {0} - Adding NSM cluster {1}'.format(alba_backend.name, nsm_cluster_name))

                        # One of the NSM nodes is overloaded. This means the complete NSM is considered overloaded
                        # Figure out which StorageRouters are the least occupied
                        loads = sorted(nsm_storagerouters.values())[:safety]
                        storagerouters = []
                        for storagerouter, load in nsm_storagerouters.iteritems():
                            if load in loads:
                                storagerouters.append(storagerouter)
                            if len(storagerouters) == safety:
                                break
                        # Creating a new NSM cluster
                        for sub_index, storagerouter in enumerate(storagerouters):
                            nsm_storagerouters[storagerouter] += 1
                            storagerouter.invalidate_dynamics('partition_config')
                            partition = DiskPartition(storagerouter.partition_config[DiskPartition.ROLES.DB][0])
                            arakoon_installer = ArakoonInstaller(cluster_name=nsm_cluster_name)
                            if sub_index == 0:
                                AlbaController._logger.debug('ALBA Backend {0} - Creating NSM cluster {1}'.format(alba_backend.name, nsm_cluster_name))
                                arakoon_installer.create_cluster(cluster_type=ServiceType.ARAKOON_CLUSTER_TYPES.NSM,
                                                                 ip=storagerouter.ip,
                                                                 base_dir=partition.folder,
                                                                 plugins={AlbaController.NSM_PLUGIN: version_str})
                            else:
                                AlbaController._logger.debug('ALBA Backend {0} - Extending NSM cluster {1}'.format(alba_backend.name, nsm_cluster_name))
                                arakoon_installer.load()
                                arakoon_installer.extend_cluster(new_ip=storagerouter.ip,
                                                                 base_dir=partition.folder,
                                                                 plugins={AlbaController.NSM_PLUGIN: version_str})
                            AlbaController._logger.debug('ALBA Backend {0} - Linking plugins'.format(alba_backend.name))
                            AlbaController._link_plugins(client=storagerouter_cache[storagerouter],
                                                         data_dir=partition.folder,
                                                         plugins=[AlbaController.NSM_PLUGIN],
                                                         cluster_name=nsm_cluster_name)
                            AlbaController._logger.debug('ALBA Backend {0} - Modeling services'.format(alba_backend.name))
                            AlbaController._model_service(alba_backend=alba_backend,
                                                          cluster_name=nsm_cluster_name,
                                                          ports=arakoon_installer.ports[storagerouter.ip],
                                                          storagerouter=storagerouter,
                                                          number=number)
                            if sub_index == 0:
                                AlbaController._logger.debug('ALBA Backend {0} - Starting cluster'.format(alba_backend.name))
                                arakoon_installer.start_cluster()
                            else:
                                AlbaController._logger.debug('ALBA Backend {0} - Restarting cluster'.format(alba_backend.name))
                                arakoon_installer.restart_cluster_after_extending(new_ip=storagerouter.ip)
                        AlbaController._logger.debug('ALBA Backend {0} - Registering NSM'.format(alba_backend.name))
                        AlbaController._register_nsm(abm_name=abm_cluster_name,
                                                     nsm_name=nsm_cluster_name,
                                                     ip=storagerouters[0].ip)
                        AlbaController._logger.debug('ALBA Backend {0} - Added NSM cluster {1}'.format(alba_backend.name, nsm_cluster_name))
            except Exception:
                AlbaController._logger.exception('NSM Checkup failed for Backend {0}'.format(alba_backend.name))
                failed_backends.append(alba_backend.name)
        if len(failed_backends) > 0:
            raise RuntimeError('Checking NSM failed for ALBA backends: {0}'.format(', '.join(failed_backends)))
        AlbaController._logger.info('NSM checkup finished')

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
    def _register_nsm(abm_name, nsm_name, ip):
        """
        Register the NSM service to the cluster
        :param abm_name: Name of the ABM cluster
        :type abm_name: str
        :param nsm_name: Name of the NSM cluster
        :type nsm_name: str
        :param ip: IP of node in the cluster to register
        :type ip: str
        :return: None
        """
        nsm_config_file = Configuration.get_configuration_path(ArakoonClusterConfig.CONFIG_KEY.format(nsm_name))
        abm_config_file = Configuration.get_configuration_path(ArakoonClusterConfig.CONFIG_KEY.format(abm_name))
        AlbaCLI.run(command='add-nsm-host',
                    config=abm_config_file,
                    extra_params=[nsm_config_file],
                    client=SSHClient(endpoint=ip))

    @staticmethod
    def _update_nsm(abm_name, nsm_name, ip):
        """
        Update the NSM service
        :param abm_name: Name of the ABM cluster
        :type abm_name: str
        :param nsm_name: Name of the NSM cluster
        :type nsm_name: str
        :param ip: IP of node in the cluster to update
        :type ip: str
        :return: None
        """
        nsm_config_file = Configuration.get_configuration_path(ArakoonClusterConfig.CONFIG_KEY.format(nsm_name))
        abm_config_file = Configuration.get_configuration_path(ArakoonClusterConfig.CONFIG_KEY.format(abm_name))
        AlbaCLI.run(command='update-nsm-host',
                    config=abm_config_file,
                    extra_params=[nsm_config_file],
                    client=SSHClient(endpoint=ip))

    @staticmethod
    def _update_abm_client_config(abm_name, ip):
        """
        Update the client configuration for the ABM cluster
        :param abm_name: Name of the ABM service
        :type abm_name: str
        :param ip: Any IP of a remaining node in the cluster with the correct configuration file available
        :type ip: str
        :return: None
        """
        abm_config_file = Configuration.get_configuration_path(ArakoonClusterConfig.CONFIG_KEY.format(abm_name))
        client = SSHClient(ip)
        # Try 8 times, 1st time immediately, 2nd time after 2 secs, 3rd time after 4 seconds, 4th time after 8 seconds
        # This will be up to 2 minutes
        # Reason for trying multiple times is because after a cluster has been shrunk or extended,
        # master might not be known, thus updating config might fail
        AlbaCLI.run(command='update-abm-client-config', config=abm_config_file, named_params={'attempts': 8}, client=client)

    @staticmethod
    def _model_service(alba_backend, cluster_name, ports=None, storagerouter=None, number=None):
        """
        Adds service to the model
        :param alba_backend: ALBA Backend with which the service is linked
        :type alba_backend: ovs.dal.hybrids.albabackend.AlbaBackend
        :param cluster_name: Name of the cluster the service belongs to
        :type cluster_name: str
        :param ports: Ports on which the service is listening (None if externally managed service)
        :type ports: list
        :param storagerouter: StorageRouter on which the service has been deployed (None if externally managed service)
        :type storagerouter: ovs.dal.hybrids.storagerouter.StorageRouter
        :param number: Number of the service (Only applicable for NSM services)
        :type number: int
        :return: None
        :rtype: NoneType
        """
        if ports is None:
            ports = []

        if number is None:  # Create ABM Service
            service_name = 'arakoon-{0}-abm'.format(alba_backend.name)
            service_type = ServiceTypeList.get_by_name(ServiceType.SERVICE_TYPES.ALBA_MGR)
            cluster = alba_backend.abm_cluster or ABMCluster()
            junction_service = ABMService()
        else:  # Create NSM Service
            cluster = None
            service_name = 'arakoon-{0}-nsm_{1}'.format(alba_backend.name, number)
            service_type = ServiceTypeList.get_by_name(ServiceType.SERVICE_TYPES.NS_MGR)
            for nsm_cluster in alba_backend.nsm_clusters:
                if nsm_cluster.number == number:
                    cluster = nsm_cluster
                    break
            cluster = cluster or NSMCluster()
            cluster.number = number
            junction_service = NSMService()

        AlbaController._logger.info('Model service: {0}'.format(str(service_name)))
        cluster.name = cluster_name
        cluster.alba_backend = alba_backend
        cluster.config_location = ArakoonClusterConfig.CONFIG_KEY.format(cluster_name)
        cluster.save()

        service = DalService()
        service.name = service_name
        service.type = service_type
        service.ports = ports
        service.storagerouter = storagerouter
        service.save()

        if isinstance(junction_service, ABMService):
            junction_service.abm_cluster = cluster
        else:
            junction_service.nsm_cluster = cluster
        junction_service.service = service
        junction_service.save()

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
                Configuration.set(key.format(machine_id), 9)

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
        Toolbox.verify_required_params(required_params={'backend_connection_info': (dict, {'host': (str, Toolbox.regex_ip),
                                                                                           'port': (int, {'min': 1, 'max': 65535}),
                                                                                           'username': (str, None),
                                                                                           'password': (str, None)}),
                                                        'backend_info': (dict, {'domain_guid': (str, Toolbox.regex_guid, False),
                                                                                'linked_guid': (str, Toolbox.regex_guid),
                                                                                'linked_name': (str, Toolbox.regex_vpool),
                                                                                'linked_preset': (str, Toolbox.regex_preset),
                                                                                'linked_alba_id': (str, Toolbox.regex_guid)})},
                                       actual_params=metadata)

        linked_alba_id = metadata['backend_info']['linked_alba_id']
        try:
            AlbaController.add_osds(alba_backend_guid=alba_backend_guid,
                                    osds=[{'osd_type': AlbaOSD.OSD_TYPES.ALBA_BACKEND, 'osd_id': linked_alba_id}],
                                    metadata=metadata)
        except DecommissionedException:
            return False
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

    @staticmethod
    @ovs_task(name='alba.checkup_maintenance_agents', schedule=Schedule(minute='0', hour='*'), ensure_single_info={'mode': 'CHAINED'})
    def checkup_maintenance_agents():
        """
        Check if requested nr of maintenance agents / Backend is actually present
        Add / remove as necessary
        :return: None
        """
        service_template_key = 'alba-maintenance_{0}-{1}'

        def _generate_name(_backend_name):
            unique_hash = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(16))
            return service_template_key.format(_backend_name, unique_hash)

        def _count(_service_map):
            amount = 0
            for _services in _service_map.values():
                amount += len(_services)
            return amount

        def _add_service(_node, _service_name, _abackend):
            try:
                _node.client.add_maintenance_service(name=_service_name,
                                                     alba_backend_guid=_abackend.guid,
                                                     abm_name=_abackend.abm_cluster.name)
                return True
            except Exception:
                AlbaController._logger.exception('Could not add maintenance service for {0} on {1}'.format(_abackend.name, _node.ip))
            return False

        def _remove_service(_node, _service_name, _abackend):
            _name = _abackend.name
            try:
                _node.client.remove_maintenance_service(name=_service_name)
                return True
            except Exception:
                AlbaController._logger.exception('Could not remove maintenance service for {0} on {1}'.format(_name, _node.ip))
            return False

        AlbaController._logger.info('Loading maintenance information')
        service_map = {}
        node_load = {}
        available_node_map = {}
        all_nodes = []
        for node in AlbaNodeList.get_albanodes():
            if node.type == AlbaNode.NODE_TYPES.GENERIC:
                continue

            try:
                service_names = node.client.list_maintenance_services()
            except Exception:
                AlbaController._logger.exception('* Cannot fetch maintenance information for {0}'.format(node.ip))
                continue

            for slot_info in node.stack.itervalues():
                for osd_info in slot_info['osds'].itervalues():
                    backend_guid = osd_info['claimed_by']
                    if backend_guid is not None:
                        if backend_guid not in available_node_map:
                            available_node_map[backend_guid] = set()
                        available_node_map[backend_guid].add(node)

            for service_name in service_names:
                backend_name, service_hash = service_name.split('_', 1)[1].rsplit('-', 1)  # E.g. alba-maintenance_my-backend-a4f7e3c61
                AlbaController._logger.debug('* Maintenance {0} for {1} on {2}'.format(service_hash, backend_name, node.ip))

                if backend_name not in service_map:
                    service_map[backend_name] = {}
                if node not in service_map[backend_name]:
                    service_map[backend_name][node] = []
                service_map[backend_name][node].append(service_name)

                if node not in node_load:
                    node_load[node] = 0
                node_load[node] += 1
            all_nodes.append(node)

        for alba_backend in AlbaBackendList.get_albabackends():
            if alba_backend.abm_cluster is None:
                AlbaController._logger.warning('ALBA Backend cluster {0} does not have an ABM cluster registered'.format(alba_backend.name))
                continue

            name = alba_backend.name
            AlbaController._logger.info('Generating service work log for {0}'.format(name))
            key = AlbaController.NR_OF_AGENTS_CONFIG_KEY.format(alba_backend.guid)
            if Configuration.exists(key):
                required_nr = Configuration.get(key)
            else:
                required_nr = 3
                Configuration.set(key, required_nr)
            if name not in service_map:
                service_map[name] = {}
            if alba_backend.guid not in available_node_map:
                available_node_map[alba_backend.guid] = []
            else:
                available_node_map[alba_backend.guid] = sorted(available_node_map[alba_backend.guid],
                                                               key=lambda n: node_load.get(n, 0))

            layout_key = AlbaController.AGENTS_LAYOUT_CONFIG_KEY.format(alba_backend.guid)
            layout = None
            if Configuration.exists(layout_key):
                layout = Configuration.get(layout_key)
                AlbaController._logger.debug('Specific layout requested: {0}'.format(layout))
                if not isinstance(layout, list):
                    layout = None
                    AlbaController._logger.warning('* Layout is not a list and will be ignored')
                else:
                    all_node_ids = set(node.node_id for node in all_nodes)
                    layout_set = set(layout)
                    for entry in layout_set - all_node_ids:
                        AlbaController._logger.warning('* Layout contains unknown node {0}'.format(entry))
                    if len(layout_set) == len(layout_set - all_node_ids):
                        AlbaController._logger.warning('* Layout does not contain any known nodes and will be ignored')
                        layout = None

            to_remove = {}
            to_add = {}
            if layout is None:
                # Clean out services on non-available nodes
                for node in service_map[name]:
                    if node not in available_node_map[alba_backend.guid]:
                        if node not in to_remove:
                            to_remove[node] = []
                        service_names = service_map[name][node]
                        to_remove[node] += service_names
                        service_map[name][node] = []
                        AlbaController._logger.debug('* Candidates for removal (unused node): {0} on {1}'.format(service_names, node.ip))
                # Multiple services on a single node must be cleaned
                for node, service_names in service_map[name].iteritems():
                    if len(service_names) > 1:
                        if node not in to_remove:
                            to_remove[node] = []
                        service_names = service_names[1:]
                        to_remove[node] += service_names
                        service_map[name][node] = service_names[0]
                        AlbaController._logger.debug('* Candidates for removal (too many services on node): {0} on {1}'.format(service_names, node.ip))
                # Add services if required
                if _count(service_map[name]) < required_nr:
                    for node in available_node_map[alba_backend.guid]:
                        if node not in service_map[name]:
                            if node not in to_add:
                                service_name = _generate_name(name)
                                to_add[node] = service_name
                                service_map[name][node] = [service_name]
                                AlbaController._logger.debug('* Candidate add (not enough services): {0} on {1}'.format(service_name, node.ip))
                        if _count(service_map[name]) == required_nr:
                            break
                # Remove services if required
                if _count(service_map[name]) > required_nr:
                    for node in reversed(available_node_map[alba_backend.guid]):
                        if node in service_map[name]:
                            if node not in to_remove:
                                to_remove[node] = []
                            for service_name in service_map[name][node][:]:
                                to_remove[node].append(service_name)
                                service_map[name][node].remove(service_name)
                                AlbaController._logger.debug('* Candidate removal (too many services): {0} on {1}'.format(service_name, node.ip))
                        if _count(service_map[name]) == required_nr:
                            break
                minimum = 1 if alba_backend.scaling == AlbaBackend.SCALINGS.LOCAL else required_nr
                # Make sure there's still at least one service left
                if _count(service_map[name]) == 0:
                    for node in to_remove:
                        if len(to_remove[node]) > 0:
                            service_name = to_remove[node].pop()
                            AlbaController._logger.debug('* Removing removal candidate (at least {0} service required): {1} on {2}'.format(minimum, service_name, node.ip))
                            if node not in service_map[name]:
                                service_map[name][node] = []
                            service_map[name][node].append(service_name)
                        if _count(service_map[name]) == minimum:
                            break
                    if _count(service_map[name]) < minimum and len(all_nodes) > 0:
                        for node in all_nodes:
                            if node not in to_add and node not in service_map[name]:
                                service_name = _generate_name(name)
                                to_add[node] = service_name
                                AlbaController._logger.debug('* Candidate add (at least {0} service required): {1} on {2}'.format(minimum, service_name, node.ip))
                                service_map[name][node] = [service_name]
                            if _count(service_map[name]) == minimum:
                                break
            else:
                # Remove services from obsolete nodes
                for node in service_map[name]:
                    if node.node_id not in layout:
                        if node not in to_remove:
                            to_remove[node] = []
                        service_names = service_map[name][node]
                        to_remove[node] += service_names
                        service_map[name][node] = []
                        AlbaController._logger.debug('* Candidates for removal (unspecified node): {0} on {1}'.format(service_names, node.ip))
                # Multiple services on a single node must be cleaned
                for node, service_names in service_map[name].iteritems():
                    if len(service_names) > 1:
                        if node not in to_remove:
                            to_remove[node] = []
                        service_names = service_names[1:]
                        to_remove[node] += service_names
                        service_map[name][node] = service_names[0]
                        AlbaController._logger.debug('* Candidates for removal (too many services on node): {0} on {1}'.format(service_names, node.ip))
                # Add services to required nodes
                for node in all_nodes:
                    if node.node_id in layout and node not in service_map[name]:
                        service_name = _generate_name(name)
                        to_add[node] = service_name
                        AlbaController._logger.debug('* Candidate add (specified node): {0} on {1}'.format(service_name, node.ip))
                        service_map[name][node] = [service_name]

            AlbaController._logger.info('Applying service work log for {0}'.format(name))
            made_changes = False
            for node, services in to_remove.iteritems():
                for service_name in services:
                    # noinspection PyTypeChecker
                    if _remove_service(node, service_name, alba_backend):
                        made_changes = True
                        AlbaController._logger.info('* Removed service {0} on {1}: OK'.format(service_name, node.ip))
                    else:
                        AlbaController._logger.warning('* Removed service {0} on {1}: FAIL'.format(service_name, node.ip))
            for node, service_name in to_add.iteritems():
                # noinspection PyTypeChecker
                if _add_service(node, service_name, alba_backend):
                    made_changes = True
                    AlbaController._logger.info('* Added service {0} on {1}: OK'.format(service_name, node.ip))
                else:
                    AlbaController._logger.warning('* Added service {0} on {1}: FAIL'.format(service_name, node.ip))
            if made_changes is True:
                alba_backend.invalidate_dynamics(['live_status'])
                alba_backend.backend.invalidate_dynamics(['live_status'])

            AlbaController._logger.info('Finished service work log for {0}'.format(name))

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

    @staticmethod
    def monitor_arakoon_clusters():
        """
        Get an overview of where the Arakoon clusters for each ALBA Backend have been deployed
        The overview is printed on stdout
        :return: None
        """
        try:
            while True:
                output = ['',
                          'Open vStorage - NSM/ABM debug information',
                          '=========================================',
                          'timestamp: {0}'.format(datetime.datetime.now()),
                          '']
                alba_backends = sorted(AlbaBackendList.get_albabackends(), key=lambda k: k.name)
                for sr in sorted(StorageRouterList.get_storagerouters(), key=lambda k: k.name):
                    if len([service for service in sr.services if service.type.name in [ServiceType.SERVICE_TYPES.NS_MGR, ServiceType.SERVICE_TYPES.ALBA_MGR] and service.storagerouter == sr]) == 0:
                        continue
                    output.append('+ {0} ({1})'.format(sr.name, sr.ip))
                    for alba_backend in alba_backends:
                        is_internal = alba_backend.abm_cluster.abm_services[0].service.is_internal
                        if is_internal is False:
                            output.append('    + ABM (externally managed)')
                        else:
                            abm_service = [abm_service for abm_service in alba_backend.abm_cluster.abm_services if abm_service.service.storagerouter == sr]
                            nsm_clusters = [nsm_cluster for nsm_cluster in alba_backend.nsm_clusters for nsm_service in nsm_cluster.nsm_services if nsm_service.service.storagerouter == sr]
                            if len(abm_service) > 0 or len(nsm_clusters) > 0:
                                output.append('  + {0}'.format(alba_backend.name))
                                if len(abm_service) > 0:
                                    output.append('    + ABM - port {0}'.format(abm_service[0].service.ports))
                            for nsm_cluster in sorted(nsm_clusters, key=lambda k: k.number):
                                load = None
                                try:
                                    load = AlbaController.get_load(nsm_cluster)
                                except:
                                    pass  # Don't print load when Arakoon unreachable
                                load = 'infinite' if load == float('inf') else '{0}%'.format(round(load, 2)) if load is not None else 'unknown'
                                capacity = 'infinite' if float(nsm_cluster.capacity) < 0 else float(nsm_cluster.capacity)
                                for nsm_service in nsm_cluster.nsm_services:
                                    if nsm_service.service.storagerouter != sr:
                                        continue
                                    if is_internal is True:
                                        output.append('    + NSM {0} - port {1} - capacity: {2}, load: {3}'.format(nsm_cluster.number,
                                                                                                                   nsm_service.service.ports,
                                                                                                                   capacity,
                                                                                                                   load))
                                    else:
                                        output.append('    + NSM {0} (externally managed) - capacity: {1}, load: {2}'.format(nsm_cluster.number,
                                                                                                                             capacity,
                                                                                                                             load))
                output += ['',
                           'Press ^C to exit',
                           '']
                print '\x1b[2J\x1b[H' + '\n'.join(output)
                time.sleep(1)
        except KeyboardInterrupt:
            pass
