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

from celery.schedules import crontab
from ovs.celery_run import celery
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.extensions.db.etcd.configuration import EtcdConfiguration
from ovs.extensions.plugins.albacli import AlbaCLI
from ovs.lib.helpers.decorators import ensure_single
from ovs.log.log_handler import LogHandler


class AlbaScheduledTaskController(object):
    """
    This controller contains all scheduled task code. These tasks can be
    executed at certain intervals and should be self-containing
    """
    _logger = LogHandler.get('lib', name='scheduled tasks')
    verification_schedule = 3
    verification_schedule_key = '/ovs/alba/backends/verification_schedule'
    if EtcdConfiguration.exists(verification_schedule_key):
        verification_schedule = EtcdConfiguration.get(verification_schedule_key)
    else:
        EtcdConfiguration.set(verification_schedule_key, verification_schedule)

    @staticmethod
    @celery.task(name='alba.scheduled.verify_namespaces',
                 schedule=crontab(0, 0, month_of_year='*/{0}'.format(verification_schedule)))
    @ensure_single(task_name='alba.scheduled.verify_namespaces')
    def verify_namespaces():
        """
        Verify namespaces for all backends
        """
        AlbaScheduledTaskController._logger.info('verify namespace task scheduling started')

        verification_factor = 10
        verification_factor_key = '/ovs/alba/backends/verification_factor'
        if EtcdConfiguration.exists(verification_factor_key):
            verification_factor = EtcdConfiguration.get(verification_factor_key)
        else:
            EtcdConfiguration.set(verification_factor_key, verification_factor)

        for albabackend in AlbaBackendList.get_albabackends():
            backend_name = albabackend.abm_services[0].service.name if albabackend.abm_services else albabackend.name + '-abm'
            config = 'etcd://127.0.0.1:2379/ovs/arakoon/{0}/config'.format(backend_name)
            namespaces = AlbaCLI.run(command='list-namespaces', config=config, to_json=True)
            for namespace in namespaces:
                AlbaScheduledTaskController._logger.info('verifying namespace: {0} scheduled ...'.format(namespace['name']))
                AlbaCLI.run(command='verify-namespace', config=config, factor=verification_factor, extra_params=[namespace['name'], '{0}_{1}'.format(albabackend.name, namespace['name'])])

        AlbaScheduledTaskController._logger.info('verify namespace task scheduling finished')
