# Copyright 2014 CloudFounders NV
# All rights reserved

"""
Contains the AlbaBackendViewSet
"""

from backend.serializers.serializers import FullSerializer
from rest_framework.response import Response
from backend.decorators import required_roles, return_object, return_list, load, return_task
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.lists.albabackendlist import AlbaBackendList
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

    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend)
    def add_device(self, albabackend, ip, port, serial):
        """
        Add a device to the backend, giving its ip, port and the serial
        """
        return AlbaController.add_device.delay(albabackend.guid, ip, port, serial)

    @action()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend)
    def add_unit(self, albabackend, devices):
        """
        Add a storage unit to the backend and register with alba nsm
        :param albabackend:     albabackend to add unit to
        :param devices:         list of tuples for each device containing ip, port and serial
        """
        return AlbaController.add_unit.delay(albabackend.guid, devices)

    @link()
    @required_roles(['read'])
    @load(AlbaBackend)
    def list_osds(self, albabackend, request):
        """
        Add a storage unit to the backend and register with alba nsm
        :param albabackend:     albabackend to add unit to

        Returns all osds registered to this Alba manager
        """

        page = request.QUERY_PARAMS.get('page')
        page = int(page) if page is not None and page.isdigit() else None
        contents = request.QUERY_PARAMS.get('contents')
        contents = None if contents is None else contents.split(',')

        registered_devices = AlbaController.list_osds(albabackend.guid)
        # Filter contents
        # - All properties are considered to be dynamic properties. However, it doesn't make sense to not load all
        #   dynamics, since they are all loaded anyway

        # [{"box-id": "2000",
        #   "ips": ["10.100.186.211"],
        #   "port": 8001,
        #   "kind": "Asd",
        #   "hostnames": ["::1"],
        #  "asd-id": "da44af6c-2baf-4012-972b-e11552f3bcac"}]

        if contents is not None:
            devices = []
            properties = ['box_id', 'ips', 'port', 'kind', 'asd_id']
            for device in registered_devices:
                cleaned_device = {}
                if '_dynamics' in contents or any(c in contents for c in properties):
                    for prop in properties:
                        if ('_dynamics' in contents or prop in contents) and '-{0}'.format(prop) not in contents:
                            if prop == 'ip':
                                # @todo: handling of multiple ips: OVS-1600
                                cleaned_device[prop] = device[prop[0]]
                            else:
                                cleaned_device[prop] = device[prop]
                devices.append(cleaned_device)
        else:
            devices = registered_devices

        # Paging
        items_pp = 10
        total_items = len(devices)
        page_metadata = {'total_items': total_items,
                         'current_page': 1,
                         'max_page': 1,
                         'start_number': min(1, total_items),
                         'end_number': total_items}
        if page is not None:
            max_page = int(math.ceil(total_items / (items_pp * 1.0)))
            if page > max_page:
                page = max_page
            if page == 0:
                start_number = -1
                end_number = 0
            else:
                start_number = (page - 1) * items_pp  # Index - e.g. 0 for page 1, 10 for page 2
                end_number = start_number + items_pp  # Index - e.g. 10 for page 1, 20 for page 2
            devices = devices[start_number: end_number]
            page_metadata = dict(page_metadata.items() + {'current_page': max(1, page),
                                                          'max_page': max(1, max_page),
                                                          'start_number': start_number + 1,
                                                          'end_number': min(total_items, end_number)}.items())

        # Sorting
        # - There is no sorting yet here, the devices are returned in the order they are received from the discover
        #   method, which is sorted by serial number

        result = {'data': devices,
                  '_paging': page_metadata,
                  '_contents': contents,
                  '_sorting': []}
        return Response(result, status=status.HTTP_200_OK)
