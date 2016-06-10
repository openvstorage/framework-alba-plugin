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
from subprocess import check_output, CalledProcessError
from ovs.log.log_handler import LogHandler


class AlbaCLI(object):
    """
    Wrapper for 'alba' command line interface
    """
    _run_results = {}

    @staticmethod
    def run(command, **kwargs):
        """
        Executes a command on ALBA
        """
        logger = LogHandler.get('extensions', name='albacli')
        if os.environ.get('RUNNING_UNITTESTS') == 'True':  # For unit tests we do not want to execute the actual command
            logger.debug('Running command {0} in unittest mode'.format(command))
            return AlbaCLI._run_results[command]

        debug = kwargs.pop('debug') if 'debug' in kwargs else False
        client = kwargs.pop('client') if 'client' in kwargs else None
        to_json = kwargs.pop('to_json') if 'to_json' in kwargs else False
        extra_params = kwargs.pop('extra_params') if 'extra_params' in kwargs else []
        debug_log = []
        try:
            cmd = 'export LD_LIBRARY_PATH=/usr/lib/alba; '
            cmd += '/usr/bin/alba {0}'.format(command)
            for key, value in kwargs.iteritems():
                cmd += ' --{0}={1}'.format(key.replace('_', '-'), value)
            if to_json is True:
                cmd += ' --to-json'
            for extra_param in extra_params:
                cmd += ' {0}'.format(extra_param)

            if debug is False:
                cmd += ' 2> /dev/null'
            debug_log.append('Command: {0}'.format(cmd))

            start = time.time()
            if client is None:
                try:
                    output = check_output(cmd, shell=True).strip()
                except CalledProcessError as ex:
                    if to_json is True:
                        output = json.loads(ex.output)
                        raise RuntimeError(output.get('error', {}).get('message'))
                    raise
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
            if to_json is True:
                output = json.loads(output)
                if output['success'] is True:
                    return output['result']
                raise RuntimeError(output['error']['message'])
            return output
        except Exception as ex:
            logger.exception('Error: {0}'.format(ex))
            # In case there's an exception, we always log
            for debug_line in debug_log:
                logger.debug(debug_line)
            raise
