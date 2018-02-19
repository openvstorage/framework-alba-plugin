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
    'ovs/api'
], function ($, ko, api) {

    function AlbaNodeService() {
        var self = this;
        /**
         * Loads in all backends for the current supplied data
         * @param queryParams: Additional query params. Defaults to no params
         * @param relayParams: Relay to use (Optional, defaults to no relay)
         * @returns {Promise}
         */
        self.loadAlbaNodes = function(queryParams, relayParams) {
            return api.get('alba/nodes', { queryparams: queryParams, relayParams: relayParams })
        };
        /**
         * Loads in a backend for the current supplied data
         * @param guid: Guid of the Alba Backend
         * @param queryParams: Additional query params. Defaults to no params
         * @param relayParams: Relay to use (Optional, defaults to no relay)
         * @returns {Promise}
         */
        self.loadAlbaNode = function(guid, queryParams, relayParams) {
            return api.get('alba/nodes/' + guid + '/', { queryparams: queryParams, relayParams: relayParams });
        };
        /**
         * Registers a new AlbaNode to the cluster
         * @param data: Data about the new node. This data contains the type, name and id of the new node
         * Example: data: {
                        node_id: self.data.newNode().nodeID(), -> can be undefined, a new ID is generated then
                        node_type: self.data.newNode().type(), -> can be undefined, defaults to ASD then
                        name: self.data.name() -> Can be undefined (in case of ASD type)
                    }
         * @returns: Returns a Promise which resolves in a task ID
         * @return {Promise}
         */
        self.addAlbaNode = function(data) {
            return api.post('alba/nodes', {data: data})
        };
        /**
         * Replaces an existing Alba Node with a new one
         * @param oldNodeGuid: Guid of the node to replace
         * @param newNodeID: ID of the node to replace the old node
         * @returns: Returns a Promise which resolves in a task ID
         * @return {Promise}
         */
        self.replaceAlbaNode = function(oldNodeGuid, newNodeID) {
            return api.post('alba/nodes/' + oldNodeGuid + '/replace_node', {data: {new_node_id: newNodeID}})
        };
    }
    return new AlbaNodeService();
});