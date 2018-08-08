# Copyright (C) 2018 iNuron NV
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
Shared albarakoon constants module
"""
# Config keys
CONFIG_ALBA_BACKEND_KEY = '/ovs/alba/backends/{0}'
NR_OF_AGENTS_CONFIG_KEY = '/ovs/alba/backends/{0}/maintenance/nr_of_agents'
AGENTS_LAYOUT_CONFIG_KEY = '/ovs/alba/backends/{0}/maintenance/agents_layout'
CONFIG_DEFAULT_NSM_HOSTS_KEY = '/ovs/alba/backends/default_nsm_hosts'

# Plugins
ABM_PLUGIN = 'albamgr_plugin'
NSM_PLUGIN = 'nsm_host_plugin'
ARAKOON_PLUGIN_DIR = '/usr/lib/alba'

MAX_NSM_AMOUNT = 50  # Maximum amount of NSMs for a backend
