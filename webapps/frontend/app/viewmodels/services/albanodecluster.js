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
    'ovs/api', 'ovs/shared'
], function ($, ko,
             api, shared) {

    function AlbaNodeClusterService() {
        var self = this;

        /**
         * Loads in all AlbaNodeClusters for the current supplied data
         * @param queryParams: Additional query params. Defaults to no params
         * @param relayParams: Relay to use (Optional, defaults to no relay)
         * @returns {Promise}
         */
        self.loadAlbaNodeClusters = function(queryParams, relayParams) {
            return api.get('alba/nodeclusters', { queryparams: queryParams, relayParams: relayParams })
        };
        /**
         * Loads in a backend for the current supplied data
         * @param guid: Guid of the AlbaNodeCluster
         * @param queryParams: Additional query params. Defaults to no params
         * @param relayParams: Relay to use (Optional, defaults to no relay)
         * @returns {Promise}
         */
        self.loadAlbaNodeCluster = function(guid, queryParams, relayParams) {
            return api.get('alba/nodeclusters/' + guid + '/', { queryparams: queryParams, relayParams: relayParams });
        };
        /**
         * Adds a new AlbaNodeCluster to the cluster
         * @param data: data about the cluster
         * @returns {Promise} which resolves into a task ID
         */
        self.addAlbaNodeCluster = function(data) {
            return api.post('alba/nodeclusters', { data:data })
        };
        /**
         * Registers an AlbaNode under an AlbaNodeCluster
         * @param guid: Guid of the AlbaNodeCluster
         * @param albaNodeID: ID of the AlbaNode to register under this cluster
         * @returns {Promise} which resolves into a task ID
         */
        self.registerAlbaNode = function(guid, albaNodeID) {
            return api.post('alba/nodeclusters/' + guid + '/register_node', {
                data: {
                    node_id: albaNodeID || null
                }
            })
        };
        /**
         * Registers AlbaNodes under an AlbaNodeCluster
         * @param guid: Guid of the AlbaNodeCluster
         * @param albaNodeIDs: List of IDs of the AlbaNodes to register under this cluster
         * @returns {Promise} which resolves into a task ID
         */
        self.registerAlbaNodes = function(guid, albaNodeIDs) {
            return api.post('alba/nodeclusters/' + guid + '/register_nodes', {
                data: {
                    node_ids: albaNodeIDs
                }
            })
        };
    }
    return new AlbaNodeClusterService();
});