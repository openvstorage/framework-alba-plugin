# Copyright 2014 CloudFounders NV
# All rights reserved

"""
Contains the AlbaBackendViewSet
"""

from backend.serializers.serializers import FullSerializer
from rest_framework.response import Response
from backend.decorators import required_roles, return_object, return_list, load, return_task, log
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from oauth2.toolbox import Toolbox as OAuth2Toolbox
from rest_framework.decorators import action, link
from ovs.lib.albacontroller import AlbaController

import math


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
    def list(self):
        """
        Lists all available ALBA Backends
        """
        return AlbaBackendList.get_albabackends()

    @log()
    @required_roles(['read'])
    @return_object(AlbaBackend)
    @load(AlbaBackend)
    def retrieve(self, albabackend):
        """
        Load information about a given AlbaBackend
        """
        return albabackend

    @log()
    @required_roles(['read', 'write', 'manage'])
    @load()
    def create(self, request):
        """
        Creates an AlbaBackend
        """
        serializer = FullSerializer(AlbaBackend, instance=AlbaBackend(), data=request.DATA, allow_passwords=True)
        if serializer.is_valid():
            alba_backend = serializer.object
            alba_backend.save()
            alba_backend.backend.status = 'INSTALLING'
            alba_backend.backend.save()
            storagerouter = StorageRouterList.get_masters()[0]
            AlbaController.add_cluster.delay(alba_backend.guid, storagerouter.guid)
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
        """
        return AlbaController.remove_cluster.delay(albabackend.guid)

    @action()
    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend)
    def add_units(self, albabackend, asds):
        """
        Add storage units to the backend and register with alba nsm
        :param albabackend:     albabackend to add unit to
        :param asd_ids:         list of ASD ids
        """
        return AlbaController.add_units.s(albabackend.guid, asds).apply_async(queue='ovs_masters')

    @link()
    @log()
    @required_roles(['read', 'manage'])
    @return_task()
    @load(AlbaBackend)
    def get_config_metadata(self, albabackend):
        """
        Gets the configuration metadata for an Alba backend
        """
        return AlbaController.get_config_metadata.delay(albabackend.guid)

    @link()
    @log()
    @required_roles(['read'])
    @load(AlbaBackend)
    def get_available_actions(self, albabackend):
        """
        Gets a list of all available actions
        """
        actions = []
        if len(albabackend.asds) == 0:
            actions.append('REMOVE')
        return Response(actions, status=status.HTTP_200_OK)

    @action()
    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend)
    def add_preset(self, albabackend, name, compression, policies):
        """
        Adds a preset to a backend
        """
        return AlbaController.add_preset.delay(albabackend.guid, name, compression, policies)

    @action()
    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend)
    def delete_preset(self, albabackend, name):
        """
        Deletes a preset
        """
        return AlbaController.delete_preset.delay(albabackend.guid, name)
