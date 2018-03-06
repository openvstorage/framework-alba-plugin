// Copyright (C) 2017 i8uron NV
//
// This file is part of Open vStorage Open Source Edition (OSE),
// as available from
//
//      http://www.openvstorage.org and
//      http://www.openvstorage.com.
//
// This file is free software; you can redistribute it and/or modify it
// under the terms of the GNU Affero General Public License v3 (GNU AGPLv3)
// as published by the Free Software Foundation, in version 3 as it comes
// in the LICENSE.txt file of the Open vStorage OSE distribution.
//
// Open vStorage is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY of any kind.
/*global define */
/**
 * Service to help with alba node related tasks
 */
define([
    'jquery', 'knockout',
    'ovs/api'
], function ($, ko,
             api) {

    function AlbaBackendService() {
        var self = this;
        /**
         * Loads in all AlbaBackends for the current supplied data
         * @param queryParams: Additional query params. Defaults to no params
         * @param relayParams: Relay to use (Optional, defaults to no relay)
         * @returns {Promise}
         */
        self.loadAlbaBackends = function(queryParams, relayParams) {
            return api.get('alba/backends', { queryparams: queryParams, relayParams: relayParams })
        };
        /**
         * Loads in a AlbaBackend for the current supplied data
         * @param guid: Guid of the AlbaNodeCluster
         * @param queryParams: Additional query params. Defaults to no params
         * @param relayParams: Relay to use (Optional, defaults to no relay)
         * @returns {Promise}
         */
        self.loadAlbaBackend = function(guid, queryParams, relayParams) {
            return api.get('alba/backends/' + guid + '/', { queryparams: queryParams, relayParams: relayParams });
        };
        self.loadAvailableActions = function(guid, queryParams, relayParams) {
            return api.get('alba/backends/' + self.guid() + '/get_available_actions', { queryparams: queryParams, relayParams: relayParams })
        }
    }
    return new AlbaBackendService();
});