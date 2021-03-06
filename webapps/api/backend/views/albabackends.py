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
Contains the AlbaBackendViewSet
"""
from rest_framework import viewsets
from rest_framework.decorators import action, link
from rest_framework.permissions import IsAuthenticated
from api.backend.decorators import load, log, required_roles, return_list, return_object, return_task, return_simple, extended_action
from api.backend.serializers.serializers import FullSerializer
from api.backend.toolbox import ApiToolbox
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.dal.lists.albanodelist import AlbaNodeList
from ovs_extensions.api.exceptions import HttpForbiddenException, HttpNotAcceptableException, HttpNotFoundException
from ovs.lib.alba import AlbaController
from ovs.lib.albaarakoon import AlbaArakoonController
from ovs.lib.albapreset import AlbaPresetController


class AlbaBackendViewSet(viewsets.ViewSet):
    """
    Information about ALBA Backends
    """
    permission_classes = (IsAuthenticated,)
    prefix = r'alba/backends'
    base_name = 'albabackends'
    return_exceptions = ['albabackends.destroy']

    def _validate_access(self, albabackend, request):
        _ = self
        if not ApiToolbox.access_granted(request.client,
                                         user_rights=albabackend.backend.user_rights,
                                         client_rights=albabackend.backend.client_rights):
            raise HttpForbiddenException(error_description='The requesting client has no access to this AlbaBackend',
                                         error='no_ownership')

    @log()
    @required_roles(['read'])
    @return_list(AlbaBackend)
    @load()
    def list(self, request):
        """
        Lists all available ALBA Backends:
        :param request: The raw request
        :type request: Request
        :return: All ALBA Backends for which the current user has permissions
        :rtype: list
        """
        backends = AlbaBackendList.get_albabackends()
        allowed_backends = []
        for alba_backend in backends:
            if ApiToolbox.access_granted(request.client,
                                         user_rights=alba_backend.backend.user_rights,
                                         client_rights=alba_backend.backend.client_rights):
                allowed_backends.append(alba_backend)
        return allowed_backends

    @log()
    @required_roles(['read'])
    @return_object(AlbaBackend)
    @load(AlbaBackend, validator=_validate_access)
    def retrieve(self, albabackend):
        """
        Load information about a given AlbaBackend
        :param albabackend: ALBA backend to retrieve
        :type albabackend: AlbaBackend
        :return: The requested ALBA Backend object
        :rtype: ovs.dal.hybrids.albabackend.AlbaBackend
        """
        return albabackend

    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_object(AlbaBackend, mode='created')
    @load()
    def create(self, request, version, abm_cluster=None, nsm_clusters=None):
        """
        Creates an AlbaBackend
        :param request: Data regarding ALBA backend to create
        :type request: request
        :param version: version requested by the client
        :type version: int
        :param abm_cluster: ABM cluster to claim for this new ALBA Backend
        :type abm_cluster: str
        :param nsm_clusters: NSM clusters to claim for this new ALBA Backend
        :type nsm_clusters: list
        :return: The newly created ALBA Backend object
        :rtype: ovs.dal.hybrids.albabackend.AlbaBackend
        """
        if version < 3:
            request.DATA['scaling'] = 'LOCAL'
        if nsm_clusters is None:
            nsm_clusters = []

        serializer = FullSerializer(AlbaBackend, instance=AlbaBackend(), data=request.DATA, allow_passwords=True)
        alba_backend = serializer.deserialize()
        alba_backend.save()
        alba_backend.backend.status = 'INSTALLING'
        alba_backend.backend.save()
        AlbaController.add_cluster.delay(alba_backend.guid, abm_cluster, nsm_clusters)
        return alba_backend

    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend, validator=_validate_access)
    def destroy(self, albabackend):
        """
        Deletes an AlbaBackend
        :param albabackend: ALBA backend to destroy
        :type albabackend: AlbaBackend
        :return: Asynchronous result of a CeleryTask
        :rtype: celery.result.AsyncResult
        """
        return AlbaController.remove_cluster.delay(albabackend.guid)

    @action()
    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend, max_version=8, validator=_validate_access)
    def add_units(self, albabackend, osds):
        """
        Add storage units to the backend and register with alba nsm
        DEPRECATED API call - Use 'add_osds' instead
        :param albabackend: ALBA backend to add units to
        :type albabackend: AlbaBackend
        :param osds: Dict of osd_id as key, disk_id as value
        :type osds: Dict
        :return: Asynchronous result of a CeleryTask
        :rtype: celery.result.AsyncResult
        """
        # Currently backwards compatible, should be removed at some point
        # Map to fill slots for backwards compatibility
        # Old call data:
        # {osd_id: disk_id}
        osd_type = 'ASD'
        osd_info = []
        stack = None
        for osd_id, disk_alias in osds.iteritems():
            slot_id = disk_alias.split('/')[-1]
            # Add units is pushed for a single ALBA Node so stack should be fetched one
            if stack is None:
                for alba_node in AlbaNodeList.get_albanodes():
                    _stack = alba_node.stack
                    if slot_id in _stack:
                        stack = _stack
                        break
            if stack is None:
                raise HttpNotAcceptableException(error='stack_not_found',
                                                 error_description='Could not find the matching stack for slot with ID {0}'.format(slot_id))
            _osd = stack[slot_id]['osds'].get(osd_id)
            if _osd is None:
                raise HttpNotFoundException(error='osd_not_found', error_description='Could not find OSD {0} on Slot {1}'.format(osd_id, slot_id))
            osd_info.append({'slot_id': slot_id,
                             'osd_type': osd_type,
                             'ips': _osd['ips'],
                             'port': _osd['port']})
        return AlbaController.add_osds.s(albabackend.guid, osd_info).apply_async(queue='ovs_masters')

    @action()
    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend, validator=_validate_access)
    def add_osds(self, albabackend, alba_node_guid, osds):
        """
        Add storage units to the backend and register with alba nsm
        :param albabackend: ALBA backend to add units to
        :type albabackend: ovs.dal.hybrids.albabackend.AlbaBackend
        :param alba_node_guid: Guid of the Alba Node on which the OSDs are added
        :type alba_node_guid: str
        :param osds: List of OSD information objects (containing: ips, port)
        :type osds: list
        :return: Asynchronous result of a CeleryTask
        :rtype: celery.result.AsyncResult
        """
        return AlbaController.add_osds.s(alba_backend_guid=albabackend.guid, osds=osds, alba_node_guid=alba_node_guid).apply_async(queue='ovs_masters')

    @action()
    @log()
    @required_roles(['write', 'manage'])
    @return_task()
    @load(AlbaBackend, validator=_validate_access)
    def update_osds(self, osds, alba_node_guid):
        """
        Update OSDs that are already registered on an ALBA Backend
        Currently used to update the IPs on which the OSD should be exposed
        :param osds: List of OSD information objects [ [osd_id, osd_data],  ]
        :type osds: list
        :param alba_node_guid: Guid of the Alba Node on which the OSDs reside
        :type alba_node_guid: str
        :return: Asynchronous result of a CeleryTask
        :rtype: celery.result.AsyncResult
        """
        return AlbaController.update_osds.s(osds=osds, alba_node_guid=alba_node_guid).apply_async()

    @link()
    @log()
    @required_roles(['read', 'manage'])
    @return_task()
    @load(AlbaBackend, validator=_validate_access)
    def get_config_metadata(self, albabackend):
        """
        Gets the configuration metadata for an Alba backend
        :param albabackend: ALBA backend to retrieve metadata for
        :type albabackend: AlbaBackend
        :return: Asynchronous result of a CeleryTask
        :rtype: celery.result.AsyncResult
        """
        return AlbaController.get_arakoon_config.delay(albabackend.guid)

    @link()
    @log()
    @required_roles(['read'])
    @return_simple()
    @load(AlbaBackend, validator=_validate_access)
    def get_available_actions(self, albabackend):
        """
        Gets a list of all available actions
        :param albabackend: ALBA backend to retrieve available actions for
        :type albabackend: AlbaBackend
        :return: List of available actions
        :rtype: list
        """
        actions = []
        if len(albabackend.osds) == 0:
            actions.append('REMOVE')
        return actions

    @action()
    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend, validator=_validate_access)
    def add_preset(self, albabackend, name, compression, policies, encryption, fragment_size=None):
        """
        Adds a preset to a backend
        :param albabackend: ALBA backend to add preset for
        :type albabackend: AlbaBackend
        :param name: Name of preset
        :type name: str
        :param compression: Compression type
        :type compression: str
        :param policies: Policies linked to the preset
        :type policies: list
        :param encryption: Encryption type
        :type encryption: str
        :param fragment_size: Size of a fragment in bytes
        :type fragment_size: int
        :return: Asynchronous result of a CeleryTask
        :rtype: celery.result.AsyncResult
        """
        return AlbaPresetController.add_preset.delay(albabackend.guid, str(name), compression, policies, encryption, fragment_size)

    @action()
    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend, validator=_validate_access)
    def delete_preset(self, albabackend, name):
        """
        Deletes a preset
        :param albabackend: ALBA backend to delete present from
        :type albabackend: AlbaBackend
        :param name: Name of preset to delete
        :type name: str
        :return: Asynchronous result of a CeleryTask
        :rtype: celery.result.AsyncResult
        """
        return AlbaPresetController.delete_preset.delay(albabackend.guid, str(name))

    @action()
    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend, validator=_validate_access)
    def update_preset(self, albabackend, name, policies):
        """
        Updates a preset's policies to a backend
        :param albabackend: ALBA backend to update preset for
        :type albabackend: AlbaBackend
        :param name: Name of preset
        :type name: str
        :param policies: Policies to set
        :type policies: list
        :return: Asynchronous result of a CeleryTask
        :rtype: celery.result.AsyncResult
        """
        return AlbaPresetController.update_preset.delay(albabackend.guid, str(name), policies)

    @link()
    @log()
    @required_roles(['read'])
    @return_task()
    @load(AlbaBackend, validator=_validate_access)
    def calculate_safety(self, albabackend, asd_id=None, osd_id=None):
        """
        Returns the safety resulting the removal of a given disk
        DEPRECATED API PARAMS: asd_id is a deprecated param. Use osd_id instead
        :param albabackend: ALBA backend to calculate safety for
        :type albabackend: AlbaBackend
        :param asd_id: ID of the OSD to calculate safety off
        :type asd_id: str
        :param osd_id: ID of the OSD to calculate safety off
        :type osd_id: str
        :return: Asynchronous result of a CeleryTask
        :rtype: celery.result.AsyncResult
        """
        return AlbaController.calculate_safety.delay(albabackend.guid, [osd_id if osd_id is not None else asd_id])

    @action()
    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend, validator=_validate_access)
    def link_alba_backends(self, albabackend, metadata, local_storagerouter, request):
        """
        Link a GLOBAL ALBA Backend to a LOCAL or another GLOBAL ALBA Backend
        :param albabackend: ALBA backend to link another ALBA Backend to
        :type albabackend: AlbaBackend
        :param metadata: Metadata about the linked ALBA Backend
        :type metadata: dict
        :param local_storagerouter: The local storagerouter
        :type local_storagerouter: StorageRouter
        :param request: Raw request
        :type request: Request
        :return: Asynchronous result of a CeleryTask
        :rtype: celery.result.AsyncResult
        """
        if 'backend_connection_info' not in metadata:
            raise HttpNotAcceptableException(error='invalid_data',
                                             error_description='Invalid metadata passed')
        connection_info = metadata['backend_connection_info']
        if connection_info['host'] == '':
            client = None
            for _client in request.client.user.clients:
                if _client.ovs_type == 'INTERNAL' and _client.grant_type == 'CLIENT_CREDENTIALS':
                    client = _client
            if client is None:
                raise HttpNotAcceptableException(error='invalid_data',
                                                 error_description='Invalid metadata passed')
            connection_info['client_id'] = client.client_id
            connection_info['client_secret'] = client.client_secret
            connection_info['host'] = local_storagerouter.ip
            connection_info['port'] = 443
        return AlbaController.link_alba_backends.s(alba_backend_guid=albabackend.guid,
                                                   metadata=metadata).apply_async(queue='ovs_masters')

    @action()
    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend, validator=_validate_access)
    def unlink_alba_backends(self, albabackend, linked_guid):
        """
        Unlink a LOCAL or GLOBAL ALBA Backend from a GLOBAL ALBA Backend
        :param albabackend: ALBA backend to unlink another LOCAL or GLOBAL ALBA Backend from
        :type albabackend: AlbaBackend
        :param linked_guid: Guid of the GLOBAL or LOCAL ALBA Backend which will be unlinked (Can be a local or a remote ALBA Backend)
        :type linked_guid: str
        :return: Asynchronous result of a CeleryTask
        :rtype: celery.result.AsyncResult
        """
        return AlbaController.unlink_alba_backends.s(target_guid=albabackend.guid,
                                                     linked_guid=linked_guid).apply_async(queue='ovs_masters')

    @action()
    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend, validator=_validate_access)
    def expand_nsm_clusters(self, albabackend, version, cluster_names=None, amount=0):
        """
        Internally managed NSM Arakoon clusters: Deploy and claim additional NSM Arakoon clusters
        Externally managed NSM Arakoon clusters: Claim additional NSM Arakoon clusters (Cluster names to claim can be passed in using the 'cluster_names' keyword)
        :param albabackend: ALBA Backend to expand the amount of NSM Arakoon clusters
        :type albabackend: ovs.dal.hybrids.albabackend.AlbaBackend
        :param version: Version requested by the client
        :type version: int
        :param cluster_names: Names of the cluster to claim (Only applicable for externally managed NSM Arakoon clusters)
        :type cluster_names: list
        :param amount: Amount of additional NSM clusters to deploy
        :type amount: int
        :return: Asynchronous result of a CeleryTask
        :rtype: celery.result.AsyncResult
        """
        if cluster_names is None:
            cluster_names = []
        if version >= 10 and amount > 0:
            raise HttpNotAcceptableException(error='invalid_data',
                                             error_description="Parameter 'amount' has been deprecated since API version 10")
        if not isinstance(cluster_names, list):
            raise HttpNotAcceptableException(error='invalid_data',
                                             error_description="Cluster names passed should be of type 'list'")
        return AlbaArakoonController.nsm_checkup.delay(alba_backend_guid=albabackend.guid, external_nsm_cluster_names=cluster_names)

    @action()
    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_simple()
    @load(AlbaBackend, validator=_validate_access)
    def set_maintenance_config(self, albabackend, maintenance_config):
        # type : (AlbaBackend, int) -> None
        """
        Set the maintenance config for the Backend
        :param albabackend: ALBA Backend to set the maintenance config for
        :type albabackend: ovs.dal.hybrids.albabackend.AlbaBackend
        :param maintenance_config: Maintenance config as it should be set
        Possible keys:
        - auto_cleanup_deleted_namespaces: Number of days to wait before cleaning up. Setting to 0 means disabling the auto cleanup
        and always clean up a namespace after removing it (int)
        :type maintenance_config: dict
        :return: Asynchronous result of a CeleryTask
        :rtype: celery.result.AsyncResult
        """
        # API implementation can be changed in the future. The whole config is sent through the API but only one setting is used
        days = maintenance_config.get('auto_cleanup_deleted_namespaces')
        if not isinstance(days, int) or 0 > days:
            raise HttpNotAcceptableException(error='invalid_data',
                                             error_description="'auto_cleanup_deleted_namespaces' should be a positive integer or 0")
        return AlbaController.set_auto_cleanup(alba_backend_guid=albabackend.guid, days=days)

    @link()
    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_simple()
    @load(AlbaBackend, validator=_validate_access)
    def get_maintenance_config(self, albabackend):
        # type : (AlbaBackend, int) -> dict
        """
        Set the maintenance config for the Backend
        :param albabackend: ALBA Backend to set the maintenance config for
        :type albabackend: ovs.dal.hybrids.albabackend.AlbaBackend
        :return: Dict that represents the config
        :rtype: dict
        """
        return AlbaController.get_maintenance_config(alba_backend_guid=albabackend.guid)

    @extended_action(methods=['get'], detail=False)
    @log()
    @return_simple()
    @required_roles(['read', 'write', 'manage'])
    @load()
    def get_maintenance_metadata(self):
        # type: () -> dict
        """
        Return a maintenance layout that the GUI can interpret to create a dynamic form
        :return: Dict with metadata
        :rtype: dict
        """
        metadata = {}
        if AlbaController.can_set_auto_cleanup():
            metadata.update({'edit': True,
                             'edit_metadata': {'auto_cleanup_deleted_namespaces': 'integer'}})
        return metadata
