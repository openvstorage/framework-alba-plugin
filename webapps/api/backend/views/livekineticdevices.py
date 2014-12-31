# Copyright 2014 CloudFounders NV
# All rights reserved

"""
Contains the LiveKineticDeviceViewSet
"""

import re
import math
from backend.decorators import required_roles, load
from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from ovs.lib.storagebackend import StorageBackendController
from rest_framework.exceptions import NotAcceptable

class LiveKineticDeviceViewSet(viewsets.ViewSet):
    """
    Information about live Kinetic devices
    """
    permission_classes = (IsAuthenticated,)
    prefix = r'alba/livekineticdevices'
    base_name = 'livekineticdevices'

    @required_roles(['read'])
    @load()
    def list(self, request, fresh=False):
        """
        Lists all Kinetic devices that can be discovered
        """
        page = request.QUERY_PARAMS.get('page')
        page = int(page) if page is not None and page.isdigit() else None
        contents = request.QUERY_PARAMS.get('contents')
        contents = None if contents is None else contents.split(',')

        found_devices = StorageBackendController.discover.delay(interval=11, fresh=fresh).get()
        # Filter contents
        # - All properties are considered to be dynamic properties. However, it doesn't make sense to not load all
        #   dynamics, since they are all loaded anyway
        if contents is not None:
            devices = []
            properties = ['network_interfaces', 'utilization', 'temperature', 'capacity',
                          'configuration', 'statistics', 'limits', 'serialNumber']
            for device in found_devices:
                cleaned_device = {}
                if '_dynamics' in contents or any(c in contents for c in properties):
                    for prop in properties:
                        if ('_dynamics' in contents or prop in contents) and '-{0}'.format(prop) not in contents:
                            cleaned_device[prop] = device[prop]
                devices.append(cleaned_device)
        else:
            devices = found_devices

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

    @required_roles(['read'])
    @load()
    def retrieve(self, pk):
        """
        Load information about a given live Kinetic device.

        The primary key here is actually a fake guid containing the ip and port:
        E.g. 10.100.169.100 port 1803 would be encoded like: 00000010-0100-0169-0100-000000001803
        """
        if re.match('^[0-9]{8}\-[0-9]{4}\-[0-9]{4}\-[0-9]{4}\-[0-9]{12}$', pk):
            pieces = pk.split('-')
            ip = '{0}.{1}.{2}.{3}'.format(int(pieces[0]), int(pieces[1]), int(pieces[2]), int(pieces[3]))
            port = int(pieces[4])
            return Response(KineticDeviceController.get_device_info.delay(ip, port).get(), status=status.HTTP_200_OK)
        raise NotAcceptable('Invalid key (should be a guid where the first 4 parts represent the ip, and the last one the port. E.g. 192.168.1.100 port 8123 would be 00000192-0168-0001-0100-000000008123)')
