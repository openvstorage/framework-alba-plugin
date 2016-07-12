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
import select
import string
from subprocess import Popen, PIPE, CalledProcessError
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
            cmd_list = ['/usr/bin/alba', command]
            for key, value in kwargs.iteritems():
                cmd_list.append('--{0}={1}'.format(key.replace('_', '-'), value))
            if to_json is True:
                cmd_list.append('--to-json')
            for extra_param in extra_params:
                cmd_list.append('{0}'.format(extra_param))

            cmd_string = ' '.join(cmd_list)
            debug_log.append('Command: {0}'.format(cmd_string))

            start = time.time()
            try:
                if client is None:
                    try:
                        if not hasattr(select, 'poll'):
                            import subprocess
                            subprocess._has_poll = False  # Damn 'monkey patching'
                        channel = Popen(cmd_list, stdout=PIPE, stderr=PIPE, universal_newlines=True)
                    except OSError as ose:
                        raise CalledProcessError(1, cmd_string, str(ose))
                    output, stderr = channel.communicate()
                    output = filter(lambda c: c in set(string.printable), output)
                    stderr_debug = 'stderr: {0}'.format(stderr)
                    stdout_debug = 'stdout: {0}'.format(output)
                    if debug is True:
                        logger.debug(stderr_debug)
                        logger.debug(stdout_debug)
                    debug_log.append(stderr_debug)
                    debug_log.append(stdout_debug)
                    exit_code = channel.returncode
                    if exit_code != 0:  # Raise same error as check_output
                        raise CalledProcessError(exit_code, cmd_string, output)
                else:
                    if debug:
                        output, stderr = client.run(cmd_list, debug=True)
                        debug_log.append('stderr: {0}'.format(stderr))
                    else:
                        output = client.run(cmd_list, debug=False).strip()
                    debug_log.append('stdout: {0}'.format(output))
            except CalledProcessError as ex:
                if to_json is True:
                    output = json.loads(ex.output)
                    raise RuntimeError(output.get('error', {}).get('message'))
                raise
            duration = time.time() - start
            if duration > 0.5:
                logger.warning('AlbaCLI call {0} took {1}s'.format(command, round(duration, 2)))
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
