# Copyright (C) 2018 iNuron NV
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
Interface module for AlbaArakoons
"""

import time
import datetime
from ovs.dal.hybrids.servicetype import ServiceType
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.dal.lists.storagerouterlist import StorageRouterList
from ovs.lib.albaarakoon import AlbaArakoonController


class AlbaArakoonInterface(object):

    @classmethod
    def monitor_arakoon_clusters(cls):
        """
        Get an overview of where the Arakoon clusters for each ALBA Backend have been deployed
        The overview is printed on stdout
        :return: None
        """
        try:
            while True:
                output = ['',
                          'Open vStorage - NSM/ABM debug information',
                          '=========================================',
                          'timestamp: {0}'.format(datetime.datetime.now()),
                          '']
                alba_backends = sorted(AlbaBackendList.get_albabackends(), key=lambda k: k.name)
                for sr in sorted(StorageRouterList.get_storagerouters(), key=lambda k: k.name):
                    if len([service for service in sr.services if service.type.name in [ServiceType.SERVICE_TYPES.NS_MGR, ServiceType.SERVICE_TYPES.ALBA_MGR] and service.storagerouter == sr]) == 0:
                        continue
                    output.append('+ {0} ({1})'.format(sr.name, sr.ip))
                    for alba_backend in alba_backends:
                        is_internal = alba_backend.abm_cluster.abm_services[0].service.is_internal
                        if is_internal is False:
                            output.append('    + ABM (externally managed)')
                        else:
                            abm_service = [abm_service for abm_service in alba_backend.abm_cluster.abm_services if abm_service.service.storagerouter == sr]
                            nsm_clusters = [nsm_cluster for nsm_cluster in alba_backend.nsm_clusters for nsm_service in nsm_cluster.nsm_services if nsm_service.service.storagerouter == sr]
                            if len(abm_service) > 0 or len(nsm_clusters) > 0:
                                output.append('  + {0}'.format(alba_backend.name))
                                if len(abm_service) > 0:
                                    output.append('    + ABM - port {0}'.format(abm_service[0].service.ports))
                            for nsm_cluster in sorted(nsm_clusters, key=lambda k: k.number):
                                load = None
                                try:
                                    load = AlbaArakoonController.get_load(nsm_cluster)
                                except:
                                    pass  # Don't print load when Arakoon unreachable
                                load = 'infinite' if load == float('inf') else '{0}%'.format(round(load, 2)) if load is not None else 'unknown'
                                capacity = 'infinite' if float(nsm_cluster.capacity) < 0 else float(nsm_cluster.capacity)
                                for nsm_service in nsm_cluster.nsm_services:
                                    if nsm_service.service.storagerouter != sr:
                                        continue
                                    if is_internal is True:
                                        output.append('    + NSM {0} - port {1} - capacity: {2}, load: {3}'.format(nsm_cluster.number, nsm_service.service.ports, capacity, load))
                                    else:
                                        output.append('    + NSM {0} (externally managed) - capacity: {1}, load: {2}'.format(nsm_cluster.number, capacity, load))
                output += ['',
                           'Press ^C to exit',
                           '']
                print '\x1b[2J\x1b[H' + '\n'.join(output)
                time.sleep(1)
        except KeyboardInterrupt:
            pass