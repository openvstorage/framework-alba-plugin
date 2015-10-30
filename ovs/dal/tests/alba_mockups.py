# Copyright 2014 iNuron NV
# All rights reserved


"""
Mockups module
"""


class AlbaCLI(object):
    """
    Mocks the AlbaCLI
    """

    run_results = {}

    def __init__(self):
        """
        Dummy init method
        """
        pass

    @staticmethod
    def run(command, *args, **kwargs):
        """
        Return fake info
        """
        _ = args, kwargs
        return AlbaCLI.run_results[command]


class AlbaCLIModule:
    """
    Mocks the AlbaCLI module
    """

    AlbaCLI = AlbaCLI
