// Copyright (C) 2017 iNuron NV
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
    'ovs/api', 'ovs/generic'
], function ($, ko, api, generic) {

    function AlbaNodeService() {
        var self = this;
        /**
         * Loads in all backends for the current supplied data
         * @param queryParams: Additional query params. Defaults to no params
         * @param relayParams: Relay to use (Optional, defaults to no relay)
         * @returns {Deferred}
         */
        self.loadAlbaNodes = function(queryParams, relayParams) {
            return api.get('alba/nodes', { queryparams: queryParams, relayParams: relayParams })
        };
        /**
         * Loads in a backend for the current supplied data
         * @param guid: Guid of the Alba Backend
         * @param queryParams: Additional query params. Defaults to no params
         * @param relayParams: Relay to use (Optional, defaults to no relay)
         * @returns {Deferred}
         */
        self.loadAlbaBackend = function(guid, queryParams, relayParams) {
            return api.get('alba/backends/' + guid + '/', { queryparams: queryParams, relayParams: relayParams });
        };
    }
    return new AlbaNodeService();
});