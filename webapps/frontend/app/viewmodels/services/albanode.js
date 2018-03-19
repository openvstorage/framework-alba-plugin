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
    'ovs/api', 'ovs/generic', 'ovs/shared'
], function ($, ko,
             api, generic, shared) {

    function AlbaNodeService() {
        var self = this;

        /**
         * Loads in all backends for the current supplied data
         * @param queryParams: Additional query params. Defaults to no params
         * @param relayParams: Relay to use (Optional, defaults to no relay)
         * @param applyDefaultSorting: Apply the default sorting (storagerouter.name, storagerouter.ip, ip)
         * @returns {Promise}
         */
        self.loadAlbaNodes = function(queryParams, relayParams, applyDefaultSorting) {
            return api.get('alba/nodes', { queryparams: queryParams, relayParams: relayParams })
                .then(function(data){
                    if (applyDefaultSorting){
                        var apiData = data.data;
                        apiData.sort(function(a, b){
                            if (![null, undefined].contains(a.storagerouter) && ![null, undefined].contains(b.storagerouter)) {
                                return a.storagerouter.name < b.storagerouter.name ? -1 : 1;
                            } else if ([null, undefined].contains(a.storagerouter) && [null, undefined].contains(b.storagerouter)) {
                                if (![undefined, null].contains(a.ip) && ![undefined, null].contains(b.ip)){
                                    return generic.ipSort(a.ip, b.ip);
                                } else {
                                    return a.node_id < b.node_id ? -1 : 1;
                                }
                            }
                            return a.storagerouter_guid !== null ? -1 : 1;
                        });
                        return data;
                    }
                    return data
                })
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
        /**
         * Removes a slot from an AlbaNode
         * Returns a Promise which resolves in data (Task is processed)
         * @param guid: Guid of the AlbaNode
         * @param slotID: ID of the slot to remove
         * @return {Promise<T>}
         */
        self.removeSlot = function(guid, slotID) {
            return api.post('alba/nodes/' + guid + '/remove_slot', { data: { slot: slotID } })
                .then(shared.tasks.wait)
        };
        /**
         * Restarts an OSD from an AlbaNode
         * Returns a Promise which resolves in data (Task is processed)
         * @param guid: Guid of the AlbaNode
         * @param osdID: ID of the OSD to restart
         * @return {Promise<T>}
         */
        self.restartOSD = function(guid, osdID) {
            return api.post('alba/nodes/' + guid + '/restart_osd', { data: { osd_id: osdID }})
                .then(shared.tasks.wait)
        };
        /**
         * Remove an AlbaNode
         * Returns a Promise which resolves in data (Task is processed)
         * @param guid: Guid of the AlbaNode
         * @return {Promise<T>}
         */
        self.deleteNode = function(guid) {
            return api.del('alba/nodes/' + guid)
                .then(shared.tasks.wait)
        };
        /**
         * Generates an empty slot for an AlbaNode
         * @param guid: Guid of the AlbaNode
         * @return {*|Promise}
         */
        self.generateEmptySlot = function(guid) {
            return api.post('alba/nodes/' + guid + '/generate_empty_slot')
        };
        /**
         * Download the log files from an AlbaNode
         * @param guid: Guid of the AlbaNode
         * @return {*|Promise<T>}
         */
        self.downloadLogFiles = function(guid) {
            return api.get('alba/nodes/' + guid + '/get_logfiles')
                .then(shared.tasks.wait)
        }
    }
    return new AlbaNodeService();
});