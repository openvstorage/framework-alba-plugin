#!/usr/bin/env python
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
class RepoMapper
"""

import os
import argparse
from subprocess import check_output, Popen, PIPE


class RepositoryResolver(object):
    """
    Class responsible for fetching the repository based on the branch that Travis is building
    """
    MAPPING = {'master': 'unstable',
               'develop': 'fwk-develop'}

    @classmethod
    def get_repository(cls, branch=None, on_travis=False):
        # type: (str, bool) -> str
        """
        Gets the repository associated with the branch travis is working on
        :param branch: Name of the branch the repository is currently on
        :type branch: str
        :param on_travis: Indicate that the script is running on an environment from Travis
        :type on_travis: bool
        :return: Name of the repository
        :rtype: str
        """
        if branch is None:
            if on_travis is True:
                branch = os.environ.get('TRAVIS_BRANCH')
            else:
                branch = check_output('git branch | grep -e "^*" | cut -d" " -f 2', shell=True).strip()
        if branch not in cls.MAPPING:
            # If the branch is not in the mapping by default, figure out it's parent
            branch = cls.determine_parent(branch, on_travis)  # Let it throw an error when it could not determine the parent
            if branch not in cls.MAPPING:
                raise RuntimeError('Unable to fetch the right release for branch {0}'.format(branch))
        return cls.MAPPING[branch]

    @classmethod
    def determine_parent(cls, branch, on_travis):
        # type: (str, bool) -> str
        """
        When working with a branch which branched of from either master or develop
        knowing which branch it was is necessary to install the correct packaged
        :param branch: Name of the branch the repository is currently on
        :type branch: str
        :param on_travis: Indicate that the script is running on an environment from Travis
        :type on_travis: bool
        :raises RunTimeError: If the parent branch name could not be found
        :return: Parent branch
        :rtype: str
        """
        # Validation
        if on_travis is True and os.environ.get('TRAVIS_PULL_REQUEST') is False:
            # Travis will be performing a merge and run the tests on the result of the merge when it's a PR
            # To currently check which apt-repo to use, we need to restore the HEAD reference by checking out the branch we would test on
            # However this would mean we'd lose the merge and thus would be testing the wrong things
            raise RuntimeError('Travis is currently not supporting pull requests on branches other than master and develop')
        cls.fetch_remote()
        parent_branch = None
        # Find the newest common ancestor (aka fork point)
        fork_point_develop = Popen(['git', 'merge-base', branch, 'origin/develop'], stdout=PIPE, stderr=PIPE).communicate()[0].strip()
        fork_point_master = Popen(['git', 'merge-base', branch, 'origin/master'], stdout=PIPE, stderr=PIPE).communicate()[0].strip()
        # Let's see what the common ancestor is of both the commit hashes
        # This hash is the point as to where either develop or master forked
        # The closest ancestor to our branch is the fork point which does not equal this one
        fork_point_between_master_develop = Popen(['git', 'merge-base', fork_point_master, fork_point_develop], stdout=PIPE, stderr=PIPE).communicate()[0].strip()
        if fork_point_between_master_develop == fork_point_develop:
            # This means master is our closet ancestor
            parent_branch = 'master'
        elif fork_point_between_master_develop == fork_point_master:
            parent_branch = 'develop'
        if parent_branch is None:
            raise RuntimeError('Could not determine the parent branch')
        return parent_branch

    @staticmethod
    def fetch_remote():
        # type: () -> None
        """
        Reconfigure the git config to fetch all remote metadata
        :return: None
        :rtype: NoneType
        """
        # Fetch references to other branches to make sure we can detect of which branch we currently branch off
        Popen(['git', 'config', '--replace-all', 'remote.origin.fetch', '+refs/heads/*:refs/remotes/origin/*'], stdout=PIPE, stderr=PIPE).communicate()
        Popen(['git', 'fetch'], stdout=PIPE, stderr=PIPE).communicate()

    @staticmethod
    def remove_prefix(text, prefix):
        # type: (str, str) -> str
        """
        Removes a given prefix from a string
        :param text: String to remove prefix from
        :type text: str
        :param prefix: Prefix to remove
        :type prefix: str
        :return: Passed in text with or without the prefix
        :rtype: str
        """
        if text.startswith(prefix):
            return text[len(prefix):]
        return text  # or whatever


if __name__ == '__main__':
    parser = argparse.ArgumentParser(prog='Repository resolver', description='Finds the closest ancestor to the current supplied branch')
    parser.add_argument('-b', '--branch', default=None, help="The branch we are currently on", type=str)
    on_travis = 'TRAVIS_BRANCH' in os.environ
    arguments = parser.parse_args()
    # Make sure it gets outputted to stdout for the Travis build to capture
    print RepositoryResolver.get_repository(branch=arguments.branch, on_travis=on_travis)
