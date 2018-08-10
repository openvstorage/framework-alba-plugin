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
AlbaBackendList module
"""
from ovs.dal.datalist import DataList
from ovs.dal.hybrids.albas3transactioncluster import S3TransactionCluster


class S3TransactionClusterList(object):
    """
    This AlbaBackendList class contains various lists regarding to the AlbaBackend class
    """

    @staticmethod
    def get_s3_transaction_clusters():
        # type: () -> DataList[S3TransactionCluster]
        """
        Returns a list of all ALBABackends
        :rtype: DataList[S3TransactionCluster]
        """
        return DataList(S3TransactionCluster, {'type': DataList.where_operator.AND,
                                      'items': []})

    @staticmethod
    def get_by_name(cluster_name):
        # type: (str) -> Union[S3TransactionCluster, None]
        """
        Gets an AlbaBackend by the alba_id
        :return: The found S3TransactionCluster if any else None
        :rtype: S3TransactionCluster or NoneType
        :raises: RuntimeError when multiple clusters were found with the specified name
        """
        items = DataList(S3TransactionCluster, {'type': DataList.where_operator.AND,
                                                   'items': [('name', DataList.operator.EQUALS, cluster_name)]})
        if len(items) > 1:
            raise RuntimeError('Multiple S3TransactionCluster found with name {0}'.format(cluster_name))
        if len(items) == 1:
            return items[0]
        return None
