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
AlbaDalHelper module
"""
from ovs.dal.hybrids.albaabmcluster import ABMCluster
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.albadisk import AlbaDisk
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.hybrids.albansmcluster import NSMCluster
from ovs.dal.hybrids.albaosd import AlbaOSD
from ovs.dal.hybrids.backend import Backend
from ovs.dal.hybrids.backendtype import BackendType
from ovs.dal.hybrids.j_abmservice import ABMService
from ovs.dal.hybrids.j_nsmservice import NSMService
from ovs.dal.hybrids.service import Service
from ovs.dal.hybrids.servicetype import ServiceType
from ovs.dal.lists.servicetypelist import ServiceTypeList
from ovs.dal.tests.helpers import DalHelper
from ovs.extensions.plugins.tests.alba_mockups import VirtualAlbaBackend
from ovs.lib.alba import AlbaController


class AlbaDalHelper(object):
    """
    This class contains functionality used by all UnitTests related to the DAL
    """
    @staticmethod
    def setup(**kwargs):
        """
        Execute several actions before starting a new UnitTest
        :param kwargs: Additional key word arguments
        :type kwargs: dict
        """
        DalHelper.setup(**kwargs)

        # noinspection PyProtectedMember
        VirtualAlbaBackend._clean()
        # noinspection PyProtectedMember
        AlbaController._add_base_configuration()

    @staticmethod
    def teardown(**kwargs):
        """
        Execute several actions when ending a UnitTest
        :param kwargs: Additional key word arguments
        :type kwargs: dict
        """
        DalHelper.teardown(**kwargs)
        # noinspection PyProtectedMember
        VirtualAlbaBackend._clean()

    @staticmethod
    def build_dal_structure(structure, previous_structure=None):
        """
        Builds a service structure
        Example:
            structure = AlbaDalHelper.build_service_structure({
                'alba_backends': [1],
                'alba_nodes': [1]
            })
        """
        if previous_structure is None:
            previous_structure = {}
        alba_osds = previous_structure.get('alba_osds', {})
        alba_nodes = previous_structure.get('alba_nodes', {})
        alba_disks = previous_structure.get('alba_disks', {})
        backend_types = previous_structure.get('backend_types', {})
        service_types = previous_structure.get('service_types', {})
        alba_backends = previous_structure.get('alba_backends', {})
        alba_abm_clusters = previous_structure.get('alba_abm_clusters', {})
        alba_nsm_clusters = previous_structure.get('alba_nsm_clusters', {})

        if 1 not in backend_types:
            backend_type = BackendType()
            backend_type.code = 'alba'
            backend_type.name = 'ALBA'
            backend_type.save()
            backend_types[1] = backend_type

        if 'AlbaManager' not in service_types:
            service_type = ServiceTypeList.get_by_name('AlbaManager')
            if service_type is None:
                service_type = ServiceType()
                service_type.name = 'AlbaManager'
                service_type.save()
            service_types['AlbaManager'] = service_type
        if 'NamespaceManager' not in service_types:
            service_type = ServiceTypeList.get_by_name('NamespaceManager')
            if service_type is None:
                service_type = ServiceType()
                service_type.name = 'NamespaceManager'
                service_type.save()
            service_types['NamespaceManager'] = service_type
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
        for ab_id in structure.get('alba_abm_clusters', ()):
            if ab_id not in alba_abm_clusters:
                if ab_id not in alba_backends:
                    raise ValueError('Non-existing ALBA Backend ID provided')
                alba_backend = alba_backends[ab_id]
                abm_cluster = ABMCluster()
                abm_cluster.name = '{0}-abm'.format(alba_backend.name)
                abm_cluster.alba_backend = alba_backend
                abm_cluster.config_location = '/ovs/arakoon/{0}-abm/config'.format(alba_backend.name)
                abm_cluster.save()
                abm_service = Service()
                abm_service.name = 'arakoon-{0}-abm'.format(alba_backend.name)
                abm_service.type = service_types['AlbaManager']
                abm_service.ports = []
                abm_service.storagerouter = None
                abm_service.save()
                abm_junction_service = ABMService()
                abm_junction_service.service = abm_service
                abm_junction_service.abm_cluster = abm_cluster
                abm_junction_service.save()
                alba_abm_clusters[ab_id] = abm_cluster
        for ab_id, amount in structure.get('alba_nsm_clusters', ()):
            if ab_id not in alba_nsm_clusters or amount != len(alba_nsm_clusters[ab_id]):
                if ab_id not in alba_backends:
                    raise ValueError('Non-existing ALBA Backend ID provided')
                alba_backend = alba_backends[ab_id]
                alba_nsm_clusters[ab_id] = []
                nsm_clusters = dict((nsm_cluster.number, nsm_cluster) for nsm_cluster in alba_backend.nsm_clusters)
                for number in range(amount):
                    if number in nsm_clusters:
                        alba_nsm_clusters[ab_id].append(nsm_clusters[number])
                        continue
                    nsm_cluster = NSMCluster()
                    nsm_cluster.name = '{0}-nsm_{1}'.format(alba_backend.name, number)
                    nsm_cluster.number = number
                    nsm_cluster.alba_backend = alba_backend
                    nsm_cluster.config_location = '/ovs/arakoon/{0}-nsm_{1}/config'.format(alba_backend.name, number)
                    nsm_cluster.save()
                    nsm_service = Service()
                    nsm_service.name = 'arakoon-{0}-nsm_{1}'.format(alba_backend.name, number)
                    nsm_service.type = service_types['NamespaceManager']
                    nsm_service.ports = []
                    nsm_service.storagerouter = None
                    nsm_service.save()
                    nsm_junction_service = NSMService()
                    nsm_junction_service.service = nsm_service
                    nsm_junction_service.nsm_cluster = nsm_cluster
                    nsm_junction_service.save()
                    alba_nsm_clusters[ab_id].append(nsm_cluster)
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
                osd.ip = '127.0.0.{0}'.format(ao_id)
                osd.port = 35000 + ao_id
                osd.save()
                alba_osds[ao_id] = osd
        return {'alba_osds': alba_osds,
                'alba_nodes': alba_nodes,
                'alba_disks': alba_disks,
                'backend_types': backend_types,
                'service_types': service_types,
                'alba_backends': alba_backends,
                'alba_abm_clusters': alba_abm_clusters,
                'alba_nsm_clusters': alba_nsm_clusters}
