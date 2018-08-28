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
Alba plugin test module
"""
import unittest
from ovs.dal.tests.helpers import DalHelper
from ovs.extensions.plugins.tests.alba_mockups import ManagerClientMockup, VirtualAlbaBackend
from ovs.dal.tests.alba_helpers import AlbaDalHelper


class AlbaGeneric(unittest.TestCase):

    def setup(self, *args, **kwargs):
        """
        Execute several actions before starting a new UnitTest
        :param kwargs: Additional key word arguments
        :type kwargs: dict
        """
        AlbaDalHelper.setup()

    def teardown(self, *args, **kwargs):
        """
        Execute several actions when ending a UnitTest
        :param kwargs: Additional key word arguments
        :type kwargs: dict
        """
        AlbaDalHelper.teardown()
        DalHelper.teardown(**kwargs)
        # noinspection PyProtectedMember
        ManagerClientMockup.clean_data()
        # noinspection PyProtectedMember
        VirtualAlbaBackend.clean_data()

    def test_api_helper_functions(self):
        structure = AlbaDalHelper.build_dal_structure({
            'alba_nodes': [1]
        })
        alba_node = structure['alba_nodes'][1]

        extractable_data_1 = {'data': 'test_data_1'}
        extractable_data_2 = 'test_data_2'
        extractable_data_3 = {'old_key': 'test_data_3'}
        self.assertEquals(ManagerClientMockup(alba_node).extract_data(response_data=extractable_data_1), 'test_data_1')
        self.assertRaises(TypeError, ManagerClientMockup(alba_node).extract_data, extractable_data_2)
        self.assertEquals(ManagerClientMockup(alba_node).extract_data(response_data=extractable_data_3, old_key='old_key'), 'test_data_3')

        extractable_data_4 = {'data': 'test_data_4',
                              '_foo': 'bar'}
        self.assertDictEqual(ManagerClientMockup(alba_node).clean(extractable_data_4), {'data': 'test_data_4'})




