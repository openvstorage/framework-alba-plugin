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

from backend.decorators import load, log, required_roles, return_list, return_object, return_task
from backend.serializers.serializers import FullSerializer
from backend.toolbox import Toolbox
from backend.exceptions import HttpForbiddenException
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.user import User
from ovs.dal.hybrids.client import Client
from ovs.dal.hybrids.j_albabackenduser import AlbaBackendUser
from ovs.dal.hybrids.j_albabackendclient import AlbaBackendClient
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
        for backend in backends:
            if Toolbox.access_granted(request.client,
                                      user_rights=backend.user_rights,
                                      client_rights=backend.client_rights):
                allowed_backends.append(backend)
        return allowed_backends

    @log()
    @required_roles(['read'])
    @return_object(AlbaBackend)
    @load(AlbaBackend)
    def retrieve(self, albabackend, request):
        """
        Load information about a given AlbaBackend
        :param albabackend: ALBA backend to retrieve
        :param request: Request object
        """
        if Toolbox.access_granted(request.client,
                                  user_rights=albabackend.user_rights,
                                  client_rights=albabackend.client_rights):
            return albabackend
        raise HttpForbiddenException(error_description='The requesting client has no access to this AlbaBackend',
                                     error='no_ownership')

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
    @load(AlbaBackend)
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
    @load(AlbaBackend)
    def add_units(self, albabackend, osds):
        """
        Add storage units to the backend and register with alba nsm
        :param albabackend: ALBA backend to add units to
        :type albabackend: AlbaBackend

        :param osds: List of OSD ids
        :type osds: list
        """
        return AlbaController.add_units.s(albabackend.guid, osds).apply_async(queue='ovs_masters')

    @link()
    @log()
    @required_roles(['read', 'manage'])
    @return_task()
    @load(AlbaBackend)
    def get_config_metadata(self, albabackend):
        """
        Gets the configuration metadata for an Alba backend
        :param albabackend: ALBA backend to retrieve metadata for
        """
        return AlbaController.get_arakoon_config.delay(albabackend.guid)

    @link()
    @log()
    @required_roles(['read'])
    @load(AlbaBackend)
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
    @load(AlbaBackend)
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
    @load(AlbaBackend)
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
    @load(AlbaBackend)
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
    @load(AlbaBackend)
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
    @load(AlbaBackend)
    def link_alba_backends(self, albabackend, metadata):
        """
        Link a GLOBAL ALBA Backend to a LOCAL or another GLOBAL ALBA Backend
        :param albabackend: ALBA backend to link another ALBA Backend to
        :type albabackend: AlbaBackend

        :param metadata: Metadata about the linked ALBA Backend
        :type metadata: dict
        """
        return AlbaController.link_alba_backends.s(alba_backend_guid=albabackend.guid,
                                                   metadata=metadata).apply_async(queue='ovs_masters')

    @action()
    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend)
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

    @action()
    @log()
    @required_roles(['manage'])
    @load(AlbaBackend)
    def configure_rights(self, albabackend, new_rights):
        """
        Configures the access rights for this backend
        :param albabackend: The backend to configure
        :type albabackend: AlbaBackend
        :param new_rights: New access rights
        :type new_rights: dict

        Example of new_rights.
        {'users': {'guida': True,
                   'guidb': True,
                   'guidc': False},
         'clients': {'guidd': False,
                     'guide': True}}
        """
        # Users
        matched_guids = []
        for user_guid, grant in new_rights.get('users', {}).iteritems():
            found = False
            for user_right in albabackend.user_rights:
                if user_right.user_guid == user_guid:
                    user_right.grant = grant
                    user_right.save()
                    matched_guids.append(user_right.guid)
                    found = True
            if found is False:
                user_right = AlbaBackendUser()
                user_right.alba_backend = albabackend
                user_right.user = User(user_guid)
                user_right.grant = grant
                user_right.save()
                matched_guids.append(user_right.guid)
        for user_right in albabackend.user_rights:
            if user_right.guid not in matched_guids:
                user_right.delete()
        # Clients
        matched_guids = []
        for client_guid, grant in new_rights.get('clients', {}).iteritems():
            found = False
            for client_right in albabackend.client_rights:
                if client_right.client_guid == client_guid:
                    client_right.grant = grant
                    client_right.save()
                    matched_guids.append(client_right.guid)
                    found = True
            if found is False:
                client_right = AlbaBackendClient()
                client_right.alba_backend = albabackend
                client_right.client = Client(client_guid)
                client_right.grant = grant
                client_right.save()
                matched_guids.append(client_right.guid)
        for client_right in albabackend.client_rights:
            if client_right.guid not in matched_guids:
                client_right.delete()
        albabackend.invalidate_dynamics(['access_rights'])
