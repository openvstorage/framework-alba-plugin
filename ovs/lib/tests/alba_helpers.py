# Copyright (C) 2017 iNuron NV
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
AlbaHelper module
"""
from ovs.extensions.plugins.tests.alba_mockups import VirtualAlbaBackend
from ovs.lib.tests.helpers import Helper


class AlbaHelper(object):
    """
    This class contains functionality used by all UnitTest related to the BLL
    """
    @staticmethod
    def setup(**kwargs):
        """
        Execute several actions before starting a new UnitTest
        :param kwargs: Additional key word arguments
        :type kwargs: dict
        """
        VirtualAlbaBackend.clean()
        return Helper.setup(**kwargs)

    @staticmethod
    def teardown(**kwargs):
        """
        Execute several actions when ending a UnitTest
        :param kwargs: Additional key word arguments
        :type kwargs: dict
        """
        VirtualAlbaBackend.clean()
        Helper.teardown(**kwargs)
