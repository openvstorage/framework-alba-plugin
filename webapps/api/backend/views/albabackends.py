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
from api.backend.decorators import load, log, required_roles, return_list, return_object, return_task, return_simple
from api.backend.serializers.serializers import FullSerializer
from api.backend.toolbox import ApiToolbox
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs_extensions.api.exceptions import HttpForbiddenException, HttpNotAcceptableException
from ovs.lib.alba import AlbaController
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
    @load(AlbaBackend, validator=_validate_access)
    def add_units(self, albabackend, osds):
        """
        Add storage units to the backend and register with alba nsm
        :param albabackend: ALBA backend to add units to
        :type albabackend: AlbaBackend
        :param osds: List of OSD ids
        :type osds: list
        :return: Asynchronous result of a CeleryTask
        :rtype: celery.result.AsyncResult
        """
        return AlbaController.add_units.s(albabackend.guid, osds).apply_async(queue='ovs_masters')

    @action()
    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend, validator=_validate_access)
    def add_osds(self, albabackend, osds):
        """
        Add storage units to the backend and register with alba nsm
        :param albabackend: ALBA backend to add units to
        :type albabackend: AlbaBackend
        :param osds: List of OSD ids
        :type osds: list
        :return: Asynchronous result of a CeleryTask
        :rtype: celery.result.AsyncResult
        """
        return AlbaController.add_osds.s(albabackend.guid, osds).apply_async(queue='ovs_masters')

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
    def calculate_safety(self, albabackend, asd_id):
        """
        Returns the safety resulting the removal of a given disk
        :param albabackend: ALBA backend to calculate safety for
        :type albabackend: AlbaBackend
        :param asd_id: ID of the ASD to calculate safety off
        :type asd_id: str
        :return: Asynchronous result of a CeleryTask
        :rtype: celery.result.AsyncResult
        """
        return AlbaController.calculate_safety.delay(albabackend.guid, [asd_id])

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
            connection_info['username'] = client.client_id
            connection_info['password'] = client.client_secret
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
    def expand_nsm_clusters(self, albabackend, cluster_names=None, amount=1):
        """
        Internally managed NSM Arakoon clusters: Deploy and claim additional NSM Arakoon clusters
        Externally managed NSM Arakoon clusters: Claim additional NSM Arakoon clusters (Cluster names to claim can be passed in using the 'cluster_names' keyword)
        :param albabackend: ALBA Backend to expand the amount of NSM Arakoon clusters
        :type albabackend: ovs.dal.hybrids.albabackend.AlbaBackend
        :param cluster_names: Names of the cluster to claim (Only applicable for externally managed NSM Arakoon clusters)
        :type cluster_names: list or None
        :param amount: Amount of additional NSM clusters to deploy
        :type amount: int
        :return: Asynchronous result of a CeleryTask
        :rtype: celery.result.AsyncResult
        """
        if cluster_names is None:
            cluster_names = []
        if not isinstance(amount, int) or not 1 <= amount <= 10:
            raise HttpNotAcceptableException(error='invalid_data',
                                             error_description="Amount passed should be of type 'int' and should be between in range 1 - 10")
        if not isinstance(cluster_names, list):
            raise HttpNotAcceptableException(error='invalid_data',
                                             error_description="Cluster names passed should be of type 'list'")
        return AlbaController.nsm_checkup.delay(alba_backend_guid=albabackend.guid, additional_nsms={'amount': amount, 'names': cluster_names})
