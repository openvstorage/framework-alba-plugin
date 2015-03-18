# Copyright 2014 CloudFounders NV
# All rights reserved

"""
AlbaBackend module
"""
from ovs.dal.dataobject import DataObject
from ovs.dal.hybrids.backend import Backend
from ovs.dal.structures import Property, Relation, Dynamic
from ovs.extensions.plugins.albacli import AlbaCLI


class AlbaBackend(DataObject):
    """
    The AlbaBackend provides ALBA specific information
    """
    __properties = [Property('alba_id', str, mandatory=False, doc='ALBA internal identifier')]
    __relations = [Relation('backend', Backend, 'alba_backend', onetoone=True, doc='Linked generic backend')]
    __dynamics = [Dynamic('all_disks', list, 5)]

    def _all_disks(self):
        """
        Returns a live list of all disks known to this AlbaBackend
        """
        from ovs.dal.lists.albanodelist import AlbaNodeList
        from ovs.dal.lists.albabackendlist import AlbaBackendList
        config_file = '/opt/OpenvStorage/config/arakoon/{0}-abm/{0}-abm.cfg'.format(self.backend.name)
        all_osds = AlbaCLI.run('list-all-osds', config=config_file, as_json=True)
        disks = []
        for node in AlbaNodeList.get_albanodes():
            for disk in node.all_disks:
                if disk['available'] is True:
                    disk['status'] = 'uninitialized'
                else:
                    if disk['state']['state'] == 'ok':
                        disk['status'] = 'initialized'
                        for osd in all_osds:
                            if osd['box_id'] == node.box_id and 'asd_id' in disk and osd['long_id'] == disk['asd_id']:
                                if osd['id'] is None:
                                    if osd['alba_id'] is None:
                                        disk['status'] = 'available'
                                    else:
                                        disk['status'] = 'unavailable'
                                        other_abackend = AlbaBackendList.get_by_alba_id(osd['alba_id'])
                                        if other_abackend is not None:
                                            disk['alba_backend_guid'] = other_abackend.guid
                                else:
                                    disk['status'] = 'claimed'
                                    disk['alba_backend_guid'] = self.guid
                    else:
                        disk['status'] = 'error'
                        disk['status_detail'] = disk['state']['detail']
                        for osd in all_osds:
                            if osd['box_id'] == node.box_id and 'asd_id' in disk and osd['long_id'] == disk['asd_id']:
                                other_abackend = AlbaBackendList.get_by_alba_id(osd['alba_id'])
                                if other_abackend is not None:
                                    disk['alba_backend_guid'] = other_abackend.guid
                disks.append(disk)
        return disks
