# Copyright 2014 CloudFounders NV
# All rights reserved

"""
Contains the AlbaBackendViewSet
"""

from backend.serializers.serializers import FullSerializer
from rest_framework.response import Response
from backend.decorators import required_roles, return_object, return_list, load
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.lists.albabackendlist import AlbaBackendList
from oauth2.toolbox import Toolbox as OAuth2Toolbox


class AlbaBackendViewSet(viewsets.ViewSet):
    """
    Information about ALBA Backends
    """
    permission_classes = (IsAuthenticated,)
    prefix = r'alba/backends'
    base_name = 'albabackends'

    @required_roles(['read'])
    @return_list(AlbaBackend)
    @load()
    def list(self):
        """
        Lists all available ALBABackends
        """
        return AlbaBackendList.get_albabackends()

    @required_roles(['read'])
    @return_object(AlbaBackend)
    @load(AlbaBackend)
    def retrieve(self, albabackend):
        """
        Load information about a given AlbaBackend
        """
        return albabackend

    @required_roles(['read', 'write', 'manage'])
    @load()
    def create(self, request):
        """
        Creates an AlbaBackend
        """
        serializer = FullSerializer(AlbaBackend, instance=AlbaBackend(), data=request.DATA, allow_passwords=True)
        if serializer.is_valid():
            alba_backend = serializer.object
            alba_backend.accesskey = OAuth2Toolbox.create_hash(32)
            alba_backend.save()
            serializer = FullSerializer(AlbaBackend, instance=alba_backend)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
