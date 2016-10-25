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
Helper module
"""
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.albadisk import AlbaDisk
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.hybrids.albaosd import AlbaOSD
from ovs.dal.hybrids.backend import Backend
from ovs.dal.hybrids.backendtype import BackendType
from ovs.dal.hybrids.j_abmservice import ABMService
from ovs.dal.hybrids.service import Service
from ovs.dal.hybrids.servicetype import ServiceType


class Helper(object):
    """
    This class contains functionality used by a bunch of tests
    """

    @staticmethod
    def build_service_structure(structure, previous_structure=None):
        """
        Builds a service structure
        Example:
            structure = Helper.build_service_structure({
                'alba_backends': [1],
                'alba_nodes': [1]
            })
        """
        if previous_structure is None:
            previous_structure = {}
        backend_types = previous_structure.get('backend_types', {})
        service_types = previous_structure.get('service_types', {})
        alba_backends = previous_structure.get('alba_backends', {})
        alba_nodes = previous_structure.get('alba_nodes', {})
        alba_disks = previous_structure.get('alba_disks', {})
        alba_osds = previous_structure.get('alba_osds', {})

        if 1 not in backend_types:
            backend_type = BackendType()
            backend_type.code = 'alba'
            backend_type.name = 'ALBA'
            backend_type.save()
            backend_types[1] = backend_type
        if 1 not in service_types:
            service_type = ServiceType()
            service_type.name = 'AlbaManager'
            service_type.save()
            service_types[1] = service_type
        for ab_id in structure.get('alba_backends', ()):
            if ab_id not in alba_backends:
                backend = Backend()
                backend.name = 'backend_{0}'.format(ab_id)
                backend.backend_type = backend_types[1]
                backend.save()
                alba_backend = AlbaBackend()
                alba_backend.backend = backend
                alba_backend.scaling = AlbaBackend.SCALINGS.LOCAL
                alba_backend.save()
                alba_backends[ab_id] = alba_backend
                service = Service()
                service.name = 'backend_{0}_abm'.format(ab_id)
                service.type = service_types[1]
                service.ports = []
                service.save()
                abm_service = ABMService()
                abm_service.service = service
                abm_service.alba_backend = alba_backend
                abm_service.save()
        for an_id in structure.get('alba_nodes', []):
            if an_id not in alba_nodes:
                alba_node = AlbaNode()
                alba_node.ip = '10.1.0.{0}'.format(an_id)
                alba_node.port = 8500
                alba_node.username = str(an_id)
                alba_node.password = str(an_id)
                alba_node.node_id = 'node_{0}'.format(an_id)
                alba_node.save()
                alba_nodes[an_id] = alba_node
        for ad_id, an_id in structure.get('alba_disks', ()):
            if ad_id not in alba_disks:
                alba_disk = AlbaDisk()
                alba_disk.aliases = ['/dev/alba_disk_{0}'.format(ad_id)]
                alba_disk.alba_node = alba_nodes[an_id]
                alba_disk.save()
                alba_disks[ad_id] = alba_disk
        for ao_id, ad_id, ab_id in structure.get('alba_osds', ()):
            if ao_id not in alba_osds:
                osd = AlbaOSD()
                osd.osd_id = 'alba_osd_{0}'.format(ao_id)
                osd.osd_type = AlbaOSD.OSD_TYPES.ASD
                osd.alba_backend = alba_backends[ab_id]
                osd.alba_disk = alba_disks[ad_id]
                osd.save()
                alba_osds[ao_id] = osd
        return {'backend_types': backend_types,
                'service_types': service_types,
                'alba_backends': alba_backends,
                'alba_nodes': alba_nodes,
                'alba_disks': alba_disks,
                'alba_osds': alba_osds}
