#!/usr/bin/env python2
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

import os

# Update ownership
os.system('chown -R ovs:ovs /opt/OpenvStorage/ovs/')

# Remove obsolete templates for rebalancer
os.system('rm -f /opt/OpenvStorage/config/templates/systemd/ovs-alba-rebalancer.conf')
os.system('rm -f /opt/OpenvStorage/config/templates/upstart/ovs-alba-rebalancer.conf')

# Remove obsolete templates for maintenance service
os.system('rm -f /opt/OpenvStorage/config/templates/systemd/ovs-alba-maintenance.conf')
os.system('rm -f /opt/OpenvStorage/config/templates/upstart/ovs-alba-maintenance.conf')
