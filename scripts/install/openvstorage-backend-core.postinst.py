#!/usr/bin/env python2
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

import os

# Update ownership
os.system('chown -R ovs:ovs /opt/OpenvStorage/ovs/')

# Remove obsolete templates for rebalancer
os.system('rm -f /opt/OpenvStorage/config/templates/systemd/ovs-alba-rebalancer.conf')
os.system('rm -f /opt/OpenvStorage/config/templates/upstart/ovs-alba-rebalancer.conf')

# Remove obsolete templates for maintenance service
os.system('rm -f /opt/OpenvStorage/config/templates/systemd/ovs-alba-maintenance.conf')
os.system('rm -f /opt/OpenvStorage/config/templates/upstart/ovs-alba-maintenance.conf')
