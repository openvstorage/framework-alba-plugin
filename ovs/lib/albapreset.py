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
AlbaPresetController module
"""

import os
import re
import json
import random
import tempfile
from ovs.dal.hybrids.albabackend import AlbaBackend
from ovs.extensions.generic.configuration import Configuration
from ovs.extensions.plugins.albacli import AlbaCLI
from ovs.lib.helpers.decorators import ovs_task
from ovs.lib.helpers.toolbox import Toolbox
from ovs.log.log_handler import LogHandler


class AlbaPresetController(object):
    """
    Contains all BLL related to ALBA presets
    """
    _logger = LogHandler.get('lib', name='albapreset')

    @staticmethod
    @ovs_task(name='alba.add_preset')
    def add_preset(alba_backend_guid, name, compression, policies, encryption, fragment_size=None):
        """
        Adds a preset to Alba
        :param alba_backend_guid: Guid of the ALBA backend
        :type alba_backend_guid: str
        :param name: Name of the preset
        :type name: str
        :param compression: Compression type for the preset (none | snappy | bz2)
        :type compression: str
        :param policies: Policies for the preset
        :type policies: list
        :param encryption: Encryption for the preset (none | aes-cbc-256 | aes-ctr-256)
        :type encryption: str
        :param fragment_size: Size of a fragment in bytes (e.g. 1048576)
        :type fragment_size: int
        :return: None
        """
        # VALIDATIONS
        if not re.match(Toolbox.regex_preset, name):
            raise ValueError('Invalid preset name specified')

        compression_options = ['snappy', 'bz2', 'none']
        if compression not in compression_options:
            raise ValueError('Invalid compression format specified, please choose from: "{0}"'.format('", "'.join(compression_options)))

        encryption_options = ['aes-cbc-256', 'aes-ctr-256', 'none']
        if encryption not in encryption_options:
            raise ValueError('Invalid encryption format specified, please choose from: "{0}"'.format('", "'.join(encryption_options)))

        if fragment_size is not None and (not isinstance(fragment_size, int) or not 16 <= fragment_size <= 1024 ** 3):
            raise ValueError('Fragment size should be a positive integer smaller than 1 GiB')

        AlbaPresetController._validate_policies_param(policies=policies)

        alba_backend = AlbaBackend(alba_backend_guid)
        if name in [preset['name'] for preset in alba_backend.presets]:
            raise RuntimeError('Preset with name {0} already exists'.format(name))

        # ADD PRESET
        preset = {'compression': compression,
                  'object_checksum': {'default': ['crc-32c'],
                                      'verify_upload': True,
                                      'allowed': [['none'], ['sha-1'], ['crc-32c']]},
                  'osds': ['all'],
                  'fragment_size': 16 * 1024 ** 2 if fragment_size is None else int(fragment_size),
                  'policies': policies,
                  'fragment_checksum': ['crc-32c'],
                  'fragment_encryption': ['none'],
                  'in_use': False,
                  'name': name}

        # Generate encryption key
        temp_key_file = None
        if encryption != 'none':
            encryption_key = ''.join(random.choice(chr(random.randint(32, 126))) for _ in range(32))
            temp_key_file = tempfile.mktemp()
            with open(temp_key_file, 'wb') as temp_file:
                temp_file.write(encryption_key)
                temp_file.flush()
            preset['fragment_encryption'] = ['{0}'.format(encryption), '{0}'.format(temp_key_file)]

        # Dump preset content on filesystem
        config = Configuration.get_configuration_path(alba_backend.abm_cluster.config_location)
        temp_config_file = tempfile.mktemp()
        with open(temp_config_file, 'wb') as data_file:
            data_file.write(json.dumps(preset))
            data_file.flush()

        # Create preset
        AlbaPresetController._logger.debug('Adding preset {0} with compression {1} and policies {2}'.format(name, compression, policies))
        AlbaCLI.run(command='create-preset', config=config, named_params={'input-url': temp_config_file}, extra_params=[name])

        # Cleanup
        alba_backend.invalidate_dynamics()
        for filename in [temp_key_file, temp_config_file]:
            if filename and os.path.exists(filename) and os.path.isfile(filename):
                os.remove(filename)

    @staticmethod
    @ovs_task(name='albapreset.delete_preset')
    def delete_preset(alba_backend_guid, name):
        """
        Deletes a preset from the Alba backend
        :param alba_backend_guid: Guid of the ALBA backend
        :type alba_backend_guid: str
        :param name: Name of the preset
        :type name: str
        :return: None
        """
        # VALIDATIONS
        alba_backend = AlbaBackend(alba_backend_guid)
        preset_default_map = dict((preset['name'], preset['is_default']) for preset in alba_backend.presets)
        if name not in preset_default_map:
            AlbaPresetController._logger.warning('Preset with name {0} for ALBA Backend {1} could not be found, so not deleting'.format(name, alba_backend.name))
            return

        if preset_default_map[name] is True:
            raise RuntimeError('Cannot delete the default preset')

        # DELETE PRESET
        AlbaPresetController._logger.debug('Deleting preset {0}'.format(name))
        config = Configuration.get_configuration_path(alba_backend.abm_cluster.config_location)
        AlbaCLI.run(command='delete-preset', config=config, extra_params=[name])
        alba_backend.invalidate_dynamics()

    @staticmethod
    @ovs_task(name='albapreset.update_preset')
    def update_preset(alba_backend_guid, name, policies):
        """
        Updates policies for an existing preset to Alba
        :param alba_backend_guid: Guid of the ALBA backend
        :type alba_backend_guid: str
        :param name: Name of preset
        :type name: str
        :param policies: New policy list to be sent to alba
        :type policies: list
        :return: None
        """
        # VALIDATIONS
        AlbaPresetController._validate_policies_param(policies=policies)

        alba_backend = AlbaBackend(alba_backend_guid)
        if name not in [preset['name'] for preset in alba_backend.presets]:
            raise RuntimeError('Could not find a preset with name {0} for ALBA Backend {1}'.format(name, alba_backend.name))

        # UPDATE PRESET
        AlbaPresetController._logger.debug('Updating preset {0} with policies {1}'.format(name, policies))
        config = Configuration.get_configuration_path(alba_backend.abm_cluster.config_location)
        temp_config_file = tempfile.mktemp()
        with open(temp_config_file, 'wb') as data_file:
            data_file.write(json.dumps({'policies': policies}))
            data_file.flush()
        AlbaCLI.run(command='update-preset', config=config, named_params={'input-url': temp_config_file}, extra_params=[name])
        alba_backend.invalidate_dynamics()
        os.remove(temp_config_file)

    @staticmethod
    def _validate_policies_param(policies):
        if len(policies) == 0:
            raise ValueError('At least 1 policy must be defined when adding/updating a preset')

        for policy in policies:
            if len(policy) != 4:
                raise ValueError('Incorrect policy format specified')

            for value in policy:
                if not isinstance(value, int):
                    raise ValueError('Policies for a preset should only contain integers')
            k = policy[0]
            m = policy[1]
            c = policy[2]
            x = policy[3]
            if k > c or c > (k + m):
                raise ValueError('Policy {0} does not match the requirement: k <= c <= (k + m)'.format(policy))
            if k == 0:
                raise ValueError('Policy {0} contains a zero k value'.format(policy))
            if c == 0:
                raise ValueError('Policy {0} contains a zero c value'.format(policy))
            if x == 0:
                raise ValueError('Policy {0} contains a zero x value'.format(policy))
