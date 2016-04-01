# Copyright 2014 iNuron NV
#
# Licensed under the Open vStorage Modified Apache License (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.openvstorage.org/license
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

logger = LogHandler.get('lib', name='scheduled tasks')


class AlbaScheduledTaskController(object):
    """
    This controller contains all scheduled task code. These tasks can be
    executed at certain intervals and should be self-containing
    """

    job_schedule_x_months = 3
    job_schedule_x_months_key = '/ovs/alba/backends/job_schedule_x_months'
    if not EtcdConfiguration.exists(job_schedule_x_months_key):
        EtcdConfiguration.set(job_schedule_x_months_key, job_schedule_x_months)

    @staticmethod
    @celery.task(name='alba.scheduled.verify_namespaces',
                 schedule=crontab(0, 0, month_of_year='*/{0}'.format(job_schedule_x_months)))
    @ensure_single(task_name='alba.scheduled.verify_namespaces')
    def verify_namespaces():
        """
        Verify namespaces for all backends
        """
        logger.info('verify namespace task scheduling started')

        job_factor = 10
        job_factor_key = '/ovs/alba/backends/job_factor'
        if EtcdConfiguration.exists(job_factor_key):
            job_factor = EtcdConfiguration.get(job_factor_key)
        else:
            EtcdConfiguration.set(job_factor_key, job_factor)

        for albabackend in AlbaBackendList.get_albabackends():
            backend_name = albabackend.abm_services[0].service.name if albabackend.abm_services else albabackend.name + '-abm'
            config = 'etcd://127.0.0.1:2379/ovs/arakoon/{0}/config'.format(backend_name)
            namespaces = AlbaCLI.run('list-namespaces', config=config, as_json=True)
            for namespace in namespaces:
                logger.info('verifying namespace: {0} scheduled ...'.format(namespace['name']))
                AlbaCLI.run('verify-namespace {0} --factor={1}'.format(namespace['name'], job_factor))

        logger.info('verify namespace task scheduling finished')
