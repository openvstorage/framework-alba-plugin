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

# Register the Alba plugin in the Open vStorage configuration file
import sys

# (Re)load plugins to make the Alba plugin available
if len(sys.argv) >= 3 and sys.argv[2] == 'configure' and (len(sys.argv) == 3 or sys.argv[3] == ''):
    # Fresh installation scenario
    from ovs.extensions.generic.plugins import PluginManager
    PluginManager.install_plugins()
