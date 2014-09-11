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
from ovs.lib.kineticdevice import KineticDeviceController
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
    def list(self, request):
        """
        Lists all Kinetic devices that can be discovered
        """
        contents = request.QUERY_PARAMS.get('contents')
        contents = None if contents is None else contents.split(',')
        page = request.QUERY_PARAMS.get('page')
        page = int(page) if page is not None and page.isdigit() else None

        devices = KineticDeviceController.discover.delay(interval=31, contents=contents).get()
        if page is not None:
            max_page = int(math.ceil(len(devices) / 10.0))
            if page > max_page:
                page = max_page
            page -= 1
            devices = devices[page * 10: (page + 1) * 10]
        return Response(devices, status=status.HTTP_200_OK)

    @required_roles(['read'])
    @load()
    def retrieve(self, pk):
        """
        Load information about a given live Kinetic device
        """
        if re.match('^[0-9]{8}\-[0-9]{4}\-[0-9]{4}\-[0-9]{4}\-[0-9]{12}$', pk):
            pieces = pk.split('-')
            ip = '{0}.{1}.{2}.{3}'.format(int(pieces[0]), int(pieces[1]), int(pieces[2]), int(pieces[3]))
            port = int(pieces[4])
            return Response(KineticDeviceController.get_device_info.delay(ip, port).get(), status=status.HTTP_200_OK)
        raise NotAcceptable('Invalid key (should be a guid where the first 4 parts represent the ip, and the last one the port. E.g. 192.168.1.100 port 8123 would be 00000192-0168-0001-0100-000000008123)')
