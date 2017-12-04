# Copyright (C) 2017 iNuron NV
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
Statsmonkey module responsible for retrieving certain statistics from the cluster and send them to an Influx DB or Redis DB
Classes: AlbaStatsMonkeyController
"""

from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.storagerouter import StorageRouter
from ovs.dal.lists.albabackendlist import AlbaBackendList
from ovs.dal.lists.storagedriverlist import StorageDriverList
from ovs.dal.lists.vpoollist import VPoolList
from ovs.extensions.generic.configuration import Configuration
from ovs.extensions.generic.logger import Logger
from ovs_extensions.monitoring.statsmonkey import StatsMonkey
from ovs.extensions.plugins.albacli import AlbaCLI
from ovs.lib.alba import AlbaController
from ovs.lib.helpers.decorators import ovs_task
from ovs.lib.helpers.toolbox import Schedule
from threading import Thread


class AlbaStatsMonkeyController(StatsMonkey):
    """
    Stats Monkey class which retrieves ALBA statistics for the cluster
    Methods:
        * run_all
        * get_stats_nsms
        * get_stats_osds
        * get_stats_vdisks
        * get_stats_proxies
        * get_stats_alba_backends
    """
    _logger = Logger(name='lib')
    _dynamic_dependencies = {'get_stats_osds': {AlbaBackend: ['osd_statistics']},  # The statistics being retrieved depend on the caching timeouts of these properties
                             'get_stats_alba_backends': {AlbaBackend: ['local_summary']}}

    _FAILOVER_MAP = {'ok_sync': 0.0,
                     'catchup': 1.0,
                     'degraded': 2.0,
                     'disabled': 0.0,
                     'ok_standalone': 0.0,
                     'checkup_required': 1.0}

    def __init__(self):
        """
        Init method. This class is a completely static class, so cannot be instantiated
        """
        raise RuntimeError('AlbaStatsMonkeyController is a static class')

    @staticmethod
    @ovs_task(name='alba.stats_monkey.run_all', schedule=Schedule(minute='*', hour='*'), ensure_single_info={"mode": "DEFAULT"})
    def run_all():
        """
        Run all the get stats methods from AlbaStatsMonkeyController
        Prerequisites when adding content:
            * New methods which need to be picked up by this method need to start with 'get_stats_'
            * New methods need to collect the information and return a bool and list of stats. Then 'run_all_get_stat_methods' method, will send the stats to the configured instance (influx / redis)
            * The frequency each method needs to be executed can be configured via the configuration management by setting the function name as key and the interval in seconds as value
            *    Eg: {'get_stats_nsms': 20}  --> Every 20 seconds, the NSM statistics will be checked upon
        """
        AlbaStatsMonkeyController.run_all_get_stat_methods()

    @classmethod
    def get_stats_nsms(cls):
        """
        Retrieve the amount of NSMs deployed and their statistics
        """
        if cls._config is None:
            cls.validate_and_retrieve_config()

        stats = []
        errors = False
        environment = cls._config['environment']
        for alba_backend in AlbaBackendList.get_albabackends():
            for nsm in alba_backend.nsm_clusters:
                stats.append({'tags': {'nsm_number': nsm.number,
                                       'environment': environment,
                                       'backend_name': alba_backend.name,
                                       'abm_service_name': alba_backend.abm_cluster.name},
                              'fields': {'load': float(AlbaController.get_load(nsm))},
                              'measurement': 'nsm'})

            config_path = Configuration.get_configuration_path(alba_backend.abm_cluster.config_location)
            try:
                nsm_host_ids = [nsm_host['id'] for nsm_host in AlbaCLI.run(command='list-nsm-hosts', config=config_path)]
                nsm_hosts_statistics = AlbaCLI.run(command='nsm-hosts-statistics', config=config_path, named_params={'nsm-hosts': ','.join(nsm_host_ids)})
                for nsm_host_id, statistics in nsm_hosts_statistics.iteritems():
                    stats.append({'tags': {'nsm_name': nsm_host_id,
                                           'environment': environment,
                                           'backend_name': alba_backend.name},
                                  'fields': cls._convert_to_float_values(statistics['statistics']),
                                  'measurement': 'nsm_statistic'})
            except Exception:
                errors = True
                cls._logger.exception('Retrieving NSM statistics for ALBA Backend {0} failed'.format(alba_backend.name))
        return errors, stats

    @classmethod
    def get_stats_proxies(cls):
        """
        Retrieve statistics for all ALBA proxies
        """
        if cls._config is None:
            cls.validate_and_retrieve_config()

        stats = []
        errors = False
        environment = cls._config['environment']
        vpool_namespace_cache = {}
        for storagedriver in StorageDriverList.get_storagedrivers():
            for alba_proxy_service in storagedriver.alba_proxies:
                ip = storagedriver.storage_ip
                port = alba_proxy_service.service.ports[0]
                try:
                    vpool = storagedriver.vpool
                    if vpool.guid not in vpool_namespace_cache:
                        vpool_namespace_cache[vpool.guid] = vpool.storagedriver_client.list_volumes(req_timeout_secs=5)
                    active_namespaces = vpool_namespace_cache[vpool.guid]
                    for namespace_stats in AlbaCLI.run(command='proxy-statistics', named_params={'host': ip, 'port': port})['ns_stats']:
                        namespace = namespace_stats[0]
                        if namespace not in active_namespaces:
                            continue

                        stats.append({'tags': {'server': storagedriver.storagerouter.name,
                                               'namespace': namespace,
                                               'vpool_name': vpool.name,
                                               'environment': environment,
                                               'backend_name': vpool.metadata['backend']['backend_info']['name'],
                                               'service_name': alba_proxy_service.service.name},
                                      'fields': cls._convert_to_float_values(namespace_stats[1]),
                                      'measurement': 'proxyperformance_namespace'})
                except Exception:
                    errors = True
                    cls._logger.exception("Failed to retrieve proxy statistics for proxy service running at {0}:{1}".format(ip, port))
        return errors, stats

    @classmethod
    def get_stats_vdisks(cls):
        """
        Retrieve statistics about all vDisks on the system.
        Check the safety, storage amount on the Backend, fail-over status and others
        """
        if cls._config is None:
            cls.validate_and_retrieve_config()

        stats = []
        errors = False
        environment = cls._config['environment']
        alba_backend_info = {}
        for alba_backend in AlbaBackendList.get_albabackends():
            config_path = Configuration.get_configuration_path(alba_backend.abm_cluster.config_location)
            disk_safety = {}
            namespace_usage = {}

            # Retrieve namespace, preset and disk safety information
            try:
                preset_info = AlbaCLI.run(command='list-presets', config=config_path)  # Not using alba_backend.presets, because it takes a whole lot longer to retrieve
                all_namespace_info = AlbaCLI.run(command='show-namespaces', config=config_path, extra_params=['--max=-1'])[1]
                all_disk_safety_info = AlbaCLI.run(command='get-disk-safety', config=config_path)
            except Exception:
                errors = True
                cls._logger.exception('Retrieving information for ALBA Backend {0} failed'.format(alba_backend.name))
                continue

            alba_backend_info[alba_backend.guid] = {'disk_safety': disk_safety,
                                                    'namespace_usage': namespace_usage}

            # Parse namespace information
            for namespace_info in all_namespace_info:
                namespace_usage[namespace_info['name']] = float(namespace_info['statistics']['storage'])

            # Parse preset information
            policies = []
            preset_name = None
            for preset in preset_info:
                if preset['in_use'] is not True:
                    continue
                preset_name = preset['name']
                policies.extend(preset['policies'])
            if preset_name is None:
                continue

            # Parse disk safety information
            total_objects = 0
            max_lost_disks = 0
            max_disk_safety = 0
            bucket_overview = {}
            disk_lost_overview = {}
            disk_safety_overview = {}
            for disk_safety_info in all_disk_safety_info:
                safety = disk_safety_info['safety']
                volume_id = disk_safety_info['namespace']
                disk_safety[volume_id] = float(safety) if safety is not None else safety

                for bucket_safety in disk_safety_info['bucket_safety']:
                    bucket = bucket_safety['bucket']
                    objects = bucket_safety['count']
                    remaining_safety = bucket_safety['remaining_safety']

                    if bucket[1] > max_lost_disks:
                        max_lost_disks = bucket[1]
                    if remaining_safety > max_disk_safety:
                        max_disk_safety = remaining_safety

                    for policy in policies:
                        k = policy[0] == bucket[0]
                        m = policy[1] == bucket[1]
                        c = policy[2] <= bucket[2]
                        x = policy[3] >= bucket[3]
                        if k and m and c and x:
                            if preset_name not in bucket_overview:
                                bucket_overview[preset_name] = {'policy': str(policy), 'presets': {}}

                    bucket[2] -= bucket_safety['applicable_dead_osds']
                    if str(bucket) not in bucket_overview[preset_name]['presets']:
                        bucket_overview[preset_name]['presets'][str(bucket)] = {'objects': 0, 'disk_safety': 0}

                    disk_lost = bucket[0] + bucket[1] - bucket[2]  # Data fragments + parity fragments - amount of fragments to write + dead osds
                    if disk_lost not in disk_lost_overview:
                        disk_lost_overview[disk_lost] = 0
                    if remaining_safety not in disk_safety_overview:
                        disk_safety_overview[remaining_safety] = 0

                    total_objects += objects
                    disk_lost_overview[disk_lost] += objects
                    disk_safety_overview[remaining_safety] += objects
                    bucket_overview[preset_name]['presets'][str(bucket)]['objects'] += objects
                    bucket_overview[preset_name]['presets'][str(bucket)]['disk_safety'] = remaining_safety

            # Create statistics regarding disk safety
            for disk_lost_number in xrange(max_lost_disks + 1):
                stats.append({'tags': {'disk_lost': disk_lost_number,
                                       'environment': environment,
                                       'backend_name': alba_backend.name},
                              'fields': {'objects': disk_lost_overview.get(disk_lost_number, 0),
                                         'total_objects': total_objects},
                              'measurement': 'disk_lost'})

            for disk_safety_number in xrange(max_disk_safety + 1):
                stats.append({'tags': {'disk_safety': disk_safety_number,
                                       'environment': environment,
                                       'backend_name': alba_backend.name},
                              'fields': {'objects': disk_safety_overview.get(disk_safety_number, 0),
                                         'total_objects': total_objects},
                              'measurement': 'disk_safety'})

            for preset_name, result in bucket_overview.iteritems():
                for bucket_count, bucket_result in result['presets'].iteritems():
                    stats.append({'tags': {'bucket': bucket_count,
                                           'policy': result['policy'],
                                           'preset_name': preset_name,
                                           'environment': environment,
                                           'disk_safety': bucket_result['disk_safety'],
                                           'backend_name': alba_backend.name},
                                  'fields': {'objects': bucket_result['objects'],
                                             'total_objects': total_objects},
                                  'measurement': 'bucket'})

        # Integrate namespace and disk safety information in vPool stats
        for vpool in VPoolList.get_vpools():
            alba_backend_guid = vpool.metadata['backend']['backend_info']['alba_backend_guid']
            for vdisk in vpool.vdisks:
                try:
                    metrics = cls._convert_to_float_values(cls._pop_realtime_info(vdisk.statistics))
                    metrics['failover_mode'] = vdisk.dtl_status
                    metrics['frontend_size'] = float(vdisk.size)
                    metrics['failover_mode_status'] = cls._FAILOVER_MAP.get(vdisk.dtl_status, 3)
                    if alba_backend_guid in alba_backend_info:
                        metrics['disk_safety'] = alba_backend_info[alba_backend_guid]['disk_safety'].get(vdisk.volume_id)
                        metrics['backend_stored'] = alba_backend_info[alba_backend_guid]['namespace_usage'].get(vdisk.volume_id)

                    stats.append({'tags': {'disk_name': vdisk.name,
                                           'volume_id': vdisk.volume_id,
                                           'vpool_name': vdisk.vpool.name,
                                           'environment': environment,
                                           'storagerouter_name': StorageRouter(vdisk.storagerouter_guid).name},
                                  'fields': metrics,
                                  'measurement': 'vdisk'})
                except Exception:
                    errors = True
                    cls._logger.exception('Retrieving statistics for vDisk {0} with guid {1} failed'.format(vdisk.name, vdisk.guid))
        return errors, stats

    @classmethod
    def get_stats_alba_backends(cls):
        """
        Retrieve statistics about all ALBA Backends and their maintenance work
        """
        if cls._config is None:
            cls.validate_and_retrieve_config()

        stats = []
        errors = False
        environment = cls._config['environment']
        for alba_backend in AlbaBackendList.get_albabackends():
            try:
                local_summary = alba_backend.local_summary
                sizes = local_summary['sizes']
                devices = local_summary['devices']
                stats.append({'tags': {'environment': environment,
                                       'backend_name': alba_backend.name},
                              'fields': {'red': int(devices['red']),
                                         'free': float(sizes['size'] - sizes['used']),
                                         'used': float(sizes['used']),
                                         'green': int(devices['green']),
                                         'orange': int(devices['orange']),
                                         'maintenance_work': int(AlbaCLI.run(command='list-work',
                                                                             config=Configuration.get_configuration_path(alba_backend.abm_cluster.config_location))['count'])},
                              'measurement': 'backend'})
            except Exception:
                errors = True
                cls._logger.exception('Retrieving statistics for ALBA Backend {0} failed'.format(alba_backend.name))
        return errors, stats

    @classmethod
    def get_stats_osds(cls):
        """
        Retrieve the OSD statistics for all ALBA Backends
        """
        def _get_stats_osds_for_alba_backend(alba_backend, statistics, errored_calls):
            try:
                for osd_id, result in alba_backend.osd_statistics.iteritems():
                    statistics.append({'tags': {'guid': alba_backend.guid,
                                                'long_id': osd_id,
                                                'environment': environment,
                                                'backend_name': alba_backend.name},
                                       'fields': cls._convert_to_float_values(result),
                                       'measurement': 'asd'})
            except Exception:
                errored_calls.append(alba_backend.name)
                cls._logger.exception('Retrieving OSD statistics failed for ALBA Backend {0}'.format(alba_backend.name))

        if cls._config is None:
            cls.validate_and_retrieve_config()

        stats = []
        errors = []
        threads = []
        environment = cls._config['environment']
        for ab in AlbaBackendList.get_albabackends():
            thread = Thread(name=ab.name, target=_get_stats_osds_for_alba_backend, args=(ab, stats, errors))
            thread.start()
            threads.append(thread)

        for thr in threads:
            thr.join(timeout=20)

        if len(errors) > 0:
            raise Exception('Retrieving OSD statistics failed for ALBA Backends:\n * {0}'.format('\n * '.join(errors)))
        return False, stats
