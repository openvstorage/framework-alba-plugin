# Copyright 2014 CloudFounders NV
# All rights reserved

"""
StorageBackendController module
"""

from ovs.celery_run import celery
from ovs.extensions.generic.storagebackend import Storagebackend
from ovs.extensions.storage.volatilefactory import VolatileFactory


class StorageBackendController(object):
    """
    Contains all generic BLL related to Storage backends
    """

    @staticmethod
    @celery.task(name='alba.storagebackend.discover')
    def discover(interval=0, fresh=False):
        """
        Discovers storage backend devices.
        """
        key = 'ovs_storagebackend_devices'
        volatile = VolatileFactory.get_client()
        data = volatile.get(key)
        if data is None or fresh is True:
            data = Storagebackend.discover(interval=interval)
            volatile.set(key, data, 300)
        return data
