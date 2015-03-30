# Copyright 2014 CloudFounders NV
# All rights reserved

"""
AlbaBackend module
"""
from ovs.dal.dataobject import DataObject
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.dal.hybrids.albanode import AlbaNode
from ovs.dal.structures import Property, Relation, Dynamic
from ovs.extensions.plugins.albacli import AlbaCLI


class AlbaASD(DataObject):
    """
    The AlbaASD represents a claimed ASD
    """
    __properties = [Property('asd_id', str, doc='ASD identifier')]
    __relations = [Relation('alba_backend', AlbaBackend, 'asds', doc='The AlbaBackend that claimed the ASD'),
                   Relation('alba_node', AlbaNode, 'asds', doc='The AlbaNode to which the ASD belongs')]
    __dynamics = [Dynamic('disk_name', str, 3600),
                  Dynamic('info', dict, 5),
                  Dynamic('statistics', dict, 5, locked=True)]

    def _disk_name(self):
        """
        Returns the name based on the asd_id
        """
        return self.info['name'] if self.info is not None else None

    def _info(self):
        """
        Returns the ASD information from its node
        """
        for disk in self.alba_node.all_disks:
            if disk['asd_id'] == self.asd_id:
                return disk

    def _statistics(self):
        """
        Loads statistics from the ASD
        """
        data_keys = ['apply', 'multi_get', 'range', 'range_entries']
        config_file = '/opt/OpenvStorage/config/arakoon/{0}-abm/{0}-abm.cfg'.format(self.alba_backend.backend.name)
        try:
            statistics = AlbaCLI.run('asd-statistics', long_id=self.asd_id, config=config_file, extra_params='--clear', as_json=True)
            for key in data_keys:
                if statistics['period'] > 0:
                    statistics[key]['n_ps'] = statistics[key]['n'] / statistics['period']
                else:
                    statistics[key]['n_ps'] = 0
                del statistics[key]['m2']
            return statistics
        except:
            # This might fail every now and then, e.g. on disk removal. Let's ignore for now.
            return None
