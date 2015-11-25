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

"""
Generic ALBA CLI module
"""
import json
from subprocess import check_output, CalledProcessError
from ovs.log.logHandler import LogHandler

logger = LogHandler.get('extensions', name='albacli')


class AlbaCLI(object):
    """
    Wrapper for 'alba' command line interface
    """

    @staticmethod
    def run(command, config=None, host=None, long_id=None, asd_port=None, node_id=None, extra_params=None,
            as_json=False, debug=False, client=None, raise_on_failure=True, attempts=None):
        """
        Executes a command on ALBA
        """
        debug_log = []
        try:
            cmd = 'export LD_LIBRARY_PATH=/usr/lib/alba; '
            cmd += '/usr/bin/alba {0}'.format(command)
            if config is not None:
                cmd += ' --config {0}'.format(config)
            if host is not None:
                cmd += ' --host {0}'.format(host)
            if long_id is not None:
                cmd += ' --long-id {0}'.format(long_id)
            if asd_port is not None:
                cmd += ' --asd-port {0}'.format(asd_port)
            if node_id is not None:
                cmd += ' --node-id {0}'.format(node_id)
            if attempts is not None:
                cmd += ' --attempts {0}'.format(attempts)
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
            debug_log.append('Command: {0}'.format(cmd))
            if client is None:
                try:
                    output = check_output(cmd, shell=True).strip()
                except CalledProcessError as ex:
                    output = ex.output
            else:
                if debug:
                    output, stderr = client.run(cmd, debug=True)
                    debug_log.append('Stderr: {0}'.format(stderr))
                else:
                    output = client.run(cmd, debug=False).strip()
                debug_log.append('Output: {0}'.format(output))
            if debug is True:
                for debug_line in debug_log:
                    logger.debug(debug_line)
            if as_json is True:
                output = json.loads(output)
                if output['success'] is True:
                    if raise_on_failure is True:
                        return output['result']
                    else:
                        return True, output['result']
                else:
                    if raise_on_failure is True:
                        raise RuntimeError(output['error']['message'])
                    else:
                        return False, output['error']
            return output
        except Exception as ex:
            logger.exception('Error: {0}'.format(ex))
            # In case there's an exception, we always log
            for debug_line in debug_log:
                logger.debug(debug_line)
            raise
