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

from backend.decorators import load, log, required_roles, return_list, return_object, return_task, return_plain
from backend.exceptions import HttpForbiddenException, HttpNotAcceptableException
from backend.serializers.serializers import FullSerializer
from backend.toolbox import Toolbox
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.lib.albacontroller import AlbaController
from rest_framework import status, viewsets
from rest_framework.decorators import action, link
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


class AlbaBackendViewSet(viewsets.ViewSet):
    """
    Information about ALBA Backends
    """
    permission_classes = (IsAuthenticated,)
    prefix = r'alba/backends'
    base_name = 'albabackends'

    def validate_access(self, albabackend, request):
        """
        :param albabackend: The AlbaBackend to validate
        :param request: The raw request
        """
        _ = self
        if not Toolbox.access_granted(request.client,
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
        Lists all available ALBA Backends
        """
        backends = AlbaBackendList.get_albabackends()
        allowed_backends = []
        for alba_backend in backends:
            if Toolbox.access_granted(request.client,
                                      user_rights=alba_backend.backend.user_rights,
                                      client_rights=alba_backend.backend.client_rights):
                allowed_backends.append(alba_backend)
        return allowed_backends

    @log()
    @required_roles(['read'])
    @return_object(AlbaBackend)
    @load(AlbaBackend, validator=validate_access)
    def retrieve(self, albabackend):
        """
        Load information about a given AlbaBackend
        :param albabackend: ALBA backend to retrieve
        """
        return albabackend

    @log()
    @required_roles(['read', 'write', 'manage'])
    @load()
    def create(self, request, version):
        """
        Creates an AlbaBackend
        :param request: Data regarding ALBA backend to create
        :type request: request
        :param version: version requested by the client
        :type version: int
        """
        if version < 3:
            request.DATA['scaling'] = 'LOCAL'
        serializer = FullSerializer(AlbaBackend, instance=AlbaBackend(), data=request.DATA, allow_passwords=True)
        if serializer.is_valid():
            alba_backend = serializer.object
            alba_backend.save()
            alba_backend.backend.status = 'INSTALLING'
            alba_backend.backend.save()
            AlbaController.add_cluster.delay(alba_backend.guid)
            serializer = FullSerializer(AlbaBackend, contents='', instance=alba_backend)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend, validator=validate_access)
    def destroy(self, albabackend):
        """
        Deletes an AlbaBackend
        :param albabackend: ALBA backend to destroy
        """
        return AlbaController.remove_cluster.delay(albabackend.guid)

    @action()
    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend, validator=validate_access)
    def add_units(self, albabackend, osds):
        """
        Add storage units to the backend and register with alba nsm
        :param albabackend: ALBA backend to add units to
        :param osds: List of OSD ids
        :type osds: list
        """
        return AlbaController.add_units.s(albabackend.guid, osds).apply_async(queue='ovs_masters')

    @link()
    @log()
    @required_roles(['read', 'manage'])
    @return_task()
    @load(AlbaBackend, validator=validate_access)
    def get_config_metadata(self, albabackend):
        """
        Gets the configuration metadata for an Alba backend
        :param albabackend: ALBA backend to retrieve metadata for
        """
        return AlbaController.get_arakoon_config.delay(albabackend.guid)

    @link()
    @log()
    @required_roles(['read'])
    @load(AlbaBackend, validator=validate_access)
    def get_available_actions(self, albabackend):
        """
        Gets a list of all available actions
        :param albabackend: ALBA backend to retrieve available actions for
        """
        actions = []
        if len(albabackend.osds) == 0:
            actions.append('REMOVE')
        return Response(actions, status=status.HTTP_200_OK)

    @action()
    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend, validator=validate_access)
    def add_preset(self, albabackend, name, compression, policies, encryption):
        """
        Adds a preset to a backend
        :param albabackend: ALBA backend to add preset for
        :param name: Name of preset
        :param compression: Compression type
        :param policies: Policies linked to the preset
        :param encryption: Encryption type
        """
        return AlbaController.add_preset.delay(albabackend.guid, name, compression, policies, encryption)

    @action()
    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend, validator=validate_access)
    def delete_preset(self, albabackend, name):
        """
        Deletes a preset
        :param albabackend: ALBA backend to delete present from
        :param name: Name of preset to delete
        """
        return AlbaController.delete_preset.delay(albabackend.guid, name)

    @action()
    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend, validator=validate_access)
    def update_preset(self, albabackend, name, policies):
        """
        Updates a preset's policies to a backend
        :param albabackend: ALBA backend to update preset for
        :param name: Name of preset
        :param policies: Policies to set
        """
        return AlbaController.update_preset.delay(albabackend.guid, name, policies)

    @link()
    @log()
    @required_roles(['read'])
    @return_task()
    @load(AlbaBackend, validator=validate_access)
    def calculate_safety(self, albabackend, asd_id):
        """
        Returns the safety resulting the removal of a given disk
        :param albabackend: ALBA backend to calculate safety for
        :param asd_id: ID of the ASD to calculate safety off
        """
        return AlbaController.calculate_safety.delay(albabackend.guid, [asd_id])

    @action()
    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend, validator=validate_access)
    def link_alba_backends(self, albabackend, metadata, local_storagerouter, request):
        """
        Link a GLOBAL ALBA Backend to a LOCAL or another GLOBAL ALBA Backend
        :param albabackend: ALBA backend to link another ALBA Backend to
        :type albabackend: AlbaBackend
        :param metadata: Metadata about the linked ALBA Backend
        :type metadata: dict
        :param local_storagerouter: The local storagerouter
        :param request: Raw request
        """
        if 'backend_connection_info' not in metadata:
            raise HttpNotAcceptableException(error_description='Invalid metadata passed',
                                             error='invalid_data')
        connection_info = metadata['backend_connection_info']
        if connection_info['host'] == '':
            client = None
            for _client in request.client.user.clients:
                if _client.ovs_type == 'INTERNAL' and _client.grant_type == 'CLIENT_CREDENTIALS':
                    client = _client
            if client is None:
                raise HttpNotAcceptableException(error_description='Invalid metadata passed',
                                                 error='invalid_data')
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
    @load(AlbaBackend, validator=validate_access)
    def unlink_alba_backends(self, albabackend, linked_guid):
        """
        Unlink a LOCAL or GLOBAL ALBA Backend from a GLOBAL ALBA Backend
        :param albabackend: ALBA backend to unlink another LOCAL or GLOBAL ALBA Backend from
        :type albabackend: AlbaBackend

        :param linked_guid: Guid of the GLOBAL or LOCAL ALBA Backend which will be unlinked (Can be a local or a remote ALBA Backend)
        :type linked_guid: str
        """
        return AlbaController.unlink_alba_backends.s(target_guid=albabackend.guid,
                                                     linked_guid=linked_guid).apply_async(queue='ovs_masters')
