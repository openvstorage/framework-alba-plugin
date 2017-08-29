// Copyright (C) 2016 iNuron NV
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
define([
    'jquery', 'durandal/app', 'knockout',
    'ovs/generic', 'ovs/refresher', 'ovs/api', 'ovs/shared',
    '../../containers/albanode'
], function($, app, ko,
            generic, Refresher, api, shared,
            AlbaNode) {
    "use strict";
    return function() {
        var self = this;

        // Variables
        self.generic   = generic;
        self.guard     = { authenticated: true };
        self.refresher = new Refresher();
        self.shared    = shared;

        // Handles
        self.loadStorageNodesHandle = undefined;

        // Observables
        self.storageNodes = ko.observableArray([]);

        // Functions
        self.loadStorageNodes = function() {
            return $.Deferred(function(deferred) {
                if (generic.xhrCompleted(self.loadStorageNodesHandle)) {
                    self.loadStorageNodesHandle = api.get('/alba/nodes', {queryparams: {contents: '_relations'}})
                        .done(function(data) {
                            var nodeIDs = [], nodes = {};
                            $.each(data.data, function (index, item) {
                                if (item.storagerouter_guid === null) {
                                    nodeIDs.push(item.node_id);
                                    nodes[item.node_id] = item;
                                }
                            });
                            generic.crossFiller(
                                nodeIDs, self.storageNodes,
                                function(nodeID) {
                                    return new AlbaNode(nodeID);
                                }, 'nodeID'
                            );
                            $.each(self.storageNodes(), function(index, storageNode) {
                                storageNode.fillData(nodes[storageNode.nodeID()]);
                            });
                            self.storageNodes.sort(function(node1, node2) {
                                return generic.ipSort(node1.ip(), node2.ip());
                            })
                        })
                        .fail(deferred.reject);
                }
            }).promise();
        };

        // Durandal
        self.activate = function() {
            self.refresher.init(function() {
                self.loadStorageNodes();
            }, 5000);
            self.refresher.start();
            self.refresher.run();
        };
        self.deactivate = function() {
            self.refresher.stop();
        };
    };
});
