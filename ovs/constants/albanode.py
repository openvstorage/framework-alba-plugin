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
ASD_BASE_PATH = os.path.join(os.path.sep, 'ovs', 'alba', 'asds')            #/ovs/alba/asds
ASD_CONFIG_DIR = os.path.join(ASD_BASE_PATH, '{0}')                         #/ovs/alba/asds/{0}
ASD_CONFIG = os.path.join(ASD_CONFIG_DIR, 'config.ini')                     #/ovs/alba/asds/{0}/config.raw

# ASD NODES
ASD_NODE_BASE_PATH = os.path.join(os.path.sep, 'ovs', 'alba', 'asdnodes')   #/ovs/alba/asdsnodes
ASD_NODE_CONFIG_PATH = os.path.join(ASD_NODE_BASE_PATH, '{0}, config')      #/ovs/alba/asdsnodes/{0}/config

# S3 NODES
S3_NODE_BASE_PATH = os.path.join(os.path.sep,'ovs', 'alba', 's3nodes')      #/ovs/alba/s3nodes
S3_NODE_CONFIG_PATH = os.path.join(S3_NODE_BASE_PATH, '{0}, config')        #/ovs/alba/s3nodes/{0}/config
