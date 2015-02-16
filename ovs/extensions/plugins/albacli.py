# Copyright 2015 CloudFounders NV
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

"""
Generic ALBA CLI module
"""
import json
from subprocess import check_output


class AlbaCLI(object):

    @staticmethod
    def run(command, config=None, host=None, asd_port=None, box_id=None, extra_params=None, as_json=True, debug=False, client=None):
        """
        Executes a command on ALBA
        """
        cmd  = 'export LD_LIBRARY_PATH=/usr/lib/alba; '
        cmd += '/usr/bin/alba {0}'.format(command)
        if config is not None:
            cmd += ' --config {0}'.format(config)
        if host is not None:
            cmd += ' --host {0}'.format(host)
        if asd_port is not None:
            cmd += ' --asd-port {0}'.format(asd_port)
        if box_id is not None:
            cmd += ' --box-id {0}'.format(box_id)
        if as_json is True:
            cmd += ' --to-json'
        if extra_params is not None:
            if isinstance(extra_params, list):
                for extra_param in extra_params:
                    cmd += ' {0}'.format(extra_param)
            else:
                cmd += ' {0}'.format(extra_params)
        if debug is False:
            cmd += ' 2> /dev/null'
        else:
            print '-- running command: {0}'.format(cmd)
        if client is None:
            output = check_output(cmd, shell=True).strip()
        else:
            output = client.run(cmd).strip()
        if as_json is True:
            output = json.loads(output)
        if debug is True:
            print '-- output: {0}'.format(output)
            print '--'
        return output
