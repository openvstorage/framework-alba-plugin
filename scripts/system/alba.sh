#!/usr/bin/env bash
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

cd /opt/OpenvStorage
export PYTHONPATH="/opt/OpenvStorage:/opt/OpenvStorage/webapps:${PYTHONPATH}"
export DISPLAY=:0
export OVS_LOGTYPE_OVERRIDE=file

function show_help {
    echo "Open vStorage CLI launcher for the ALBA plugin"
    echo "--------------------------"
    echo "Usage:"
    echo "  * Miscellaneous options:"
    echo "    - ovs alba help                       Show this help section"
    echo ""
    echo "  * Monitor options:"
    echo "    - ovs alba monitor clusters           Watch Open vStorage Arakoon clusters for the ALBA plugin"
    echo ""
}

if [ "$1" = "help" ] ; then
    show_help
elif [ "$1" = "monitor" ] ; then
    if [ "$2" = "clusters" ] ; then
        python -c "from ovs.lib.alba import AlbaController; AlbaController.monitor_arakoon_clusters()"
    else
        show_help
    fi
else
    show_help
fi
