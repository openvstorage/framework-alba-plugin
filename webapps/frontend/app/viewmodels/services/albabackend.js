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
         * @param guid: Guid of the AlbaBackend
         * @param queryParams: Additional query params. Defaults to no params
         * @param relayParams: Relay to use (Optional, defaults to no relay)
         * @returns {Promise}
         */
        self.loadAlbaBackend = function(guid, queryParams, relayParams) {
            return api.get('alba/backends/' + guid + '/', { queryparams: queryParams, relayParams: relayParams });
        };
        /**
         * Load all available actions of an AlbaBackend
         * @param guid: Guid of the AlbaBackend
         * @param queryParams: Additional query params. Defaults to no params
         * @param relayParams: Relay to use (Optional, defaults to no relay)
         * * @return {Promise<T>}
         */
        self.getAvailableActions = function(guid, queryParams, relayParams) {
            return api.get('alba/backends/' + guid + '/get_available_actions', { queryparams: queryParams, relayParams: relayParams })
        };
        /**
         * Register OSDs under an AlbaBackend
         * Returns a Promise which resolves into the data (task is handled)
         * @param guid: Guid of the AlbaBackend
         * @param osdData: Collection of OSD data
         * @param albaNodeGuid: Guid of the AlbaNode from which the OSDs will be added
         * @return {Promise<T>}
         */
        self.addOSDsOfNode = function(guid, osdData, albaNodeGuid) {
            return api.post('alba/backends/' + guid + '/add_osds', {
                data: {
                    osds: osdData,
                    alba_node_guid: albaNodeGuid
                }
            })
            .then(self.shared.tasks.wait)
        };
    }
    return new AlbaBackendService();
});