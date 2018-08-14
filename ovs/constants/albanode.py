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
Shared albanode constants module
"""
import os

# ASD
ASD_CONFIG_DIR = '/ovs/alba/asds/{0}'
ASD_CONFIG = '{0}/config'.format(ASD_CONFIG_DIR)

# ASD NODES
ASD_NODE_BASE_PATH = '/ovs/alba/asdnodes'
ASD_NODE_CONFIG_PATH = os.path.join(ASD_NODE_BASE_PATH, '{0}/config')

# S3 NODES
S3_NODE_BASE_PATH = '/ovs/alba/s3nodes'
S3_NODE_CONFIG_PATH = os.path.join(S3_NODE_BASE_PATH, '{0}/config')
