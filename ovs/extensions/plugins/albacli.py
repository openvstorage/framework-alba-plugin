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
import re
import json
import time
import select
import logging
from subprocess import Popen, PIPE, CalledProcessError
from ovs_extensions.constants import is_unittest_mode
from ovs.extensions.generic.logger import Logger


class AlbaError(RuntimeError):
    """
    Thrown when ALBA command was able to be executed, but execution of the command failed for whatever reason
    For more information about specific ALBA error codes, see: https://github.com/openvstorage/alba/blob/master/ocaml/src/albamgr_protocol.ml#L1473-L1504
    Currently used error codes:
        11 - OSD already claimed - albamgr_exn
        7 - OSD already added - albamgr_exn
    """
    # Error types that can be raised by alba
    ALBAMGR_EXCEPTION = 'albamgr_exn'
    UNKNOWN = 'unknown'

    def __init__(self, message, error_code, exception_type):
        super(AlbaError, self).__init__(message)
        self.error_code = error_code
        self.exception_type = exception_type

    def __str__(self):
        return '{0} - code: {1} - type: {2}'.format(self.message, self.error_code, self.exception_type)


class AlbaCLI(object):
    """
    Wrapper for 'alba' command line interface
    """
    @staticmethod
    def run(command, config=None, named_params=None, extra_params=None, client=None, debug=False, to_json=True):
        """
        Executes a command on ALBA
        When --to-json is NOT passed:
            * An error occurs --> exitcode != 0
            * It worked --> exitcode == 0

        When --to-json is passed:
            * An errors occurs during verification of parameters passed  -> exitcode != 0
            * An error occurs while executing the command --> exitcode == 0 (error in json output)
            * It worked --> exitcode == 0

        :param command: The command to execute, eg: 'list-namespaces'
        :type command: str
        :param config: The configuration location to be used, eg: 'arakoon://config/ovs/arakoon/ovsdb/config?ini=%2Fopt%2FOpenvStorage%2Fconfig%2Farakoon_cacc.ini'
        :type config: str
        :param named_params: Additional parameters to be given to the command, eg: {'long-id': ','.join(asd_ids)}
        :type named_params: dict
        :param extra_params: Additional parameters to be given to the command, eg: [name]
        :type extra_params: list
        :param client: A client on which to execute the command
        :type client: ovs_extensions.generic.sshclient.SSHClient
        :param debug: Log additional output
        :type debug: bool
        :param to_json: Request a JSON response from Alba
        :type to_json: bool
        :return: The output of the command
        :rtype: dict
        """
        if named_params is None:
            named_params = {}
        if extra_params is None:
            extra_params = []

        logger = logging.getLogger(__name__)
        if is_unittest_mode():
            # For the unittest, all commands are passed to a mocked Alba
            from ovs.extensions.plugins.tests.alba_mockups import VirtualAlbaBackend
            named_params.update({'config': config})
            named_params.update({'extra_params': extra_params})
            return getattr(VirtualAlbaBackend, command.replace('-', '_'))(**named_params)

        debug_log = []
        try:
            if to_json is True:
                extra_options = ["--to-json"]
            else:
                extra_options = []
            cmd_list = ['/usr/bin/alba', command] + extra_options
            if config is not None:
                cmd_list.append('--config={0}'.format(config))
            for key, value in named_params.iteritems():
                cmd_list.append('--{0}={1}'.format(key, value))
            cmd_list.extend(extra_params)
            cmd_string = ' '.join(cmd_list)
            debug_log.append('Command: {0}'.format(cmd_string))

            start = time.time()
            try:
                if debug is True:
                    logger.debug('Command: {0}'.format(cmd_string))
                if client is None:
                    try:
                        if not hasattr(select, 'poll'):
                            import subprocess
                            subprocess._has_poll = False  # Damn 'monkey patching'
                        channel = Popen(cmd_list, stdout=PIPE, stderr=PIPE, universal_newlines=True)
                    except OSError as ose:
                        raise CalledProcessError(1, cmd_string, str(ose))
                    output, stderr = channel.communicate()
                    output = re.sub(r'[^\x00-\x7F]+', '', output)
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
                    if debug is True:
                        output, stderr = client.run(cmd_list, debug=True, return_stderr=True)
                        debug_log.append('stderr: {0}'.format(stderr))
                    else:
                        output = client.run(cmd_list).strip()
                    debug_log.append('stdout: {0}'.format(output))

                if to_json is True:
                    output = json.loads(output)
                else:
                    return output
                duration = time.time() - start
                if duration > 0.5:
                    logger.warning('AlbaCLI call {0} took {1}s'.format(command, round(duration, 2)))
            except CalledProcessError as cpe:
                try:
                    output = json.loads(cpe.output)
                except Exception:
                    raise RuntimeError('Executing command {0} failed with output {1}'.format(cmd_string, cpe.output))

            if output['success'] is True:
                return output['result']
            raise AlbaError(output['error']['message'], output['error']['exception_code'], output['error']['exception_type'])

        except Exception as ex:
            logger.exception('Error: {0}'.format(ex))
            # In case there's an exception, we always log
            for debug_line in debug_log:
                logger.debug(debug_line)
            raise
