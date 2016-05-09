# Copyright 2016 iNuron NV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
ScheduledTaskController module
"""

from celery.schedules import crontab
from ovs.celery_run import celery
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.extensions.db.etcd.configuration import EtcdConfiguration
from ovs.extensions.plugins.albacli import AlbaCLI
from ovs.lib.helpers.decorators import ensure_single
from ovs.log.logHandler import LogHandler


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
            namespaces = AlbaCLI.run('list-namespaces', config=config, as_json=True)
            for namespace in namespaces:
                AlbaScheduledTaskController._logger.info('verifying namespace: {0} scheduled ...'.format(namespace['name']))
                AlbaCLI.run('verify-namespace {0} --factor={1}'.format(namespace['name'], verification_factor))

        AlbaScheduledTaskController._logger.info('verify namespace task scheduling finished')
