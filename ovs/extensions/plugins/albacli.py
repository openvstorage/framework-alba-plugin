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

"""
Generic ALBA CLI module
"""
import os
import json
import time
from ovs.log.log_handler import LogHandler
from subprocess import check_output, CalledProcessError


class AlbaCLI(object):
    """
    Wrapper for 'alba' command line interface
    """
    _run_results = {}

    @staticmethod
    def run(command, config=None, host=None, long_id=None, asd_port=None, node_id=None, extra_params=None,
            as_json=False, debug=False, client=None, raise_on_failure=True, attempts=None):
        """
        Executes a command on ALBA
        """
        logger = LogHandler.get('extensions', name='albacli')
        if os.environ.get('RUNNING_UNITTESTS') == 'True':  # For unit tests we do not want to execute the actual command
            logger.debug('Running command {0} in unittest mode'.format(command))
            return AlbaCLI._run_results[command]

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

            start = time.time()
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
            duration = time.time() - start
            if duration > 0.5:
                logger.warning('AlbaCLI call {0} took {1}s'.format(command, round(duration, 2)))
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
