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
ScheduledTaskController module
"""

from ovs.celery_run import celery
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.extensions.generic.configuration import Configuration
from ovs.extensions.plugins.albacli import AlbaCLI
from ovs.lib.helpers.toolbox import Schedule
from ovs.log.log_handler import LogHandler


class AlbaScheduledTaskController(object):
    """
    This controller contains all scheduled task code. These tasks can be
    executed at certain intervals and should be self-containing
    """
    _logger = LogHandler.get('lib', name='scheduled tasks')

    @staticmethod
    @celery.task(name='alba.scheduled.verify_namespaces', schedule=Schedule(minute='0', hour='0', day_of_month='1', month_of_year='*/3'))
    def verify_namespaces():
        """
        Verify namespaces for all backends
        """
        AlbaScheduledTaskController._logger.info('verify namespace task scheduling started')

        verification_factor = Configuration.get('/ovs/alba/backends/verification_factor', default=10)
        for albabackend in AlbaBackendList.get_albabackends():
            backend_name = albabackend.abm_services[0].service.name if albabackend.abm_services else albabackend.name + '-abm'
            config = Configuration.get_configuration_path('/ovs/arakoon/{0}/config'.format(backend_name))
            namespaces = AlbaCLI.run(command='list-namespaces', config=config)
            for namespace in namespaces:
                ns_name = namespace['name']
                AlbaScheduledTaskController._logger.info('verifying namespace: {0} scheduled ...'.format(ns_name))
                AlbaCLI.run(command='verify-namespace',
                            config=config,
                            named_params={'factor': verification_factor},
                            extra_params=[ns_name, '{0}_{1}'.format(albabackend.name, ns_name)])

        AlbaScheduledTaskController._logger.info('verify namespace task scheduling finished')
