#!/usr/bin/env python2
# Copyright 2015 iNuron NV
#
# Licensed under the Open vStorage Modified Apache License (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.openvstorage.org/license
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Register the Alba plugin in the Open vStorage configuration file
import sys
import json

config_filename = '/opt/OpenvStorage/config/ovs.json'
with open(config_filename, 'r') as config_file:
    contents = json.loads(config_file.read())
if 'alba' not in contents['plugins']['backends']:
    contents['plugins']['backends'].append('alba')
    with open(config_filename, 'w') as config_file:
        config_file.write(json.dumps(contents, indent=4))

# (Re)load plugins to make the Alba plugin available
if len(sys.argv) >= 3 and sys.argv[2] == 'configure' and (len(sys.argv) == 3 or sys.argv[3] == ''):
    # Fresh installation scenario
    sys.path.append('/opt/OpenvStorage')
    from ovs.extensions.generic.plugins import PluginManager
    PluginManager.install_plugins()
