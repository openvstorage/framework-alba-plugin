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
            serializer = FullSerializer(AlbaBackend, instance=alba_backend)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action()
    @log()
    @required_roles(['read', 'write', 'manage'])
    @return_task()
    @load(AlbaBackend)
    def add_units(self, albabackend, asd_ids):
        """
        Add storage units to the backend and register with alba nsm
        :param albabackend:     albabackend to add unit to
        :param asd_ids:         list of ASD ids
        """
        return AlbaController.add_units.s(albabackend.guid, asd_ids).apply_async(queue='ovs_masters')

    @link()
    @log()
    @required_roles(['read'])
    @load(AlbaBackend)
    def list_discovered_osds(self, albabackend, request):
        """
        list discovered osds that can be claimed by this backend
        :param albabackend:     albabackend to add unit to

        Returns all claimable osds
        """

        page = request.QUERY_PARAMS.get('page')
        page = int(page) if page is not None and page.isdigit() else None
        contents = request.QUERY_PARAMS.get('contents')
        contents = None if contents is None else contents.split(',')

        discovered_devices = AlbaController.list_discovered_osds(albabackend.guid)
        # Filter contents
        # - All properties are considered to be dynamic properties. However, it doesn't make sense to not load all
        #   dynamics, since they are all loaded anyway

        #  [{"box-id": "2000",
        #   "ips": ["10.100.186.211"],
        #   "port": 8001,
        #   "kind": "Asd",
        #   "long_id": "da44af6c-2baf-4012-972b-e11552f3bcac"}]

        if contents is not None:
            devices = []
            properties = ['box_id', 'ips', 'port', 'kind', 'long_id']
            for device in discovered_devices:
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
            devices = discovered_devices

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

    @link()
    @log()
    @required_roles(['read'])
    @load(AlbaBackend)
    def list_registered_osds(self, albabackend, request):
        """
        Add a storage unit to the backend and register with alba nsm
        :param albabackend:     albabackend to add unit to

        Returns all osds registered to this Alba manager
        """

        page = request.QUERY_PARAMS.get('page')
        page = int(page) if page is not None and page.isdigit() else None
        contents = request.QUERY_PARAMS.get('contents')
        contents = None if contents is None else contents.split(',')

        registered_devices = AlbaController.list_registered_osds(albabackend.guid)
        # Filter contents
        # - All properties are considered to be dynamic properties. However, it doesn't make sense to not load all
        #   dynamics, since they are all loaded anyway

        # [{"box-id": "2000",
        #   "ips": ["10.100.186.211"],
        #   "port": 8001,
        #   "kind": "Asd",
        #   "hostnames": ["::1"],
        #  "id": "da44af6c-2baf-4012-972b-e11552f3bcac"}]

        if contents is not None:
            devices = []
            properties = ['box_id', 'ips', 'port', 'kind', 'long_id']
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
