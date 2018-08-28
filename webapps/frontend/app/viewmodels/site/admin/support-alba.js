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
    'viewmodels/containers/shared/base_container', 'viewmodels/containers/albanode/albanode',
    'viewmodels/services/albanode'
], function($, app, ko,
            generic, Refresher, api, shared,
            BaseContainer, AlbaNode,
            albaNodeService) {
    "use strict";
    var viewModelMapping = {
        storageNodes: {
            key: function(data) {  // For relation updates: check if the GUID has changed before discarding a model
                return ko.utils.unwrapObservable(data.node_id)
            },
            create: function(options) {
                return new AlbaNode(options.data);
            }
        }
    };

    /**
     * SupportAlba viewModel
     */
    function SupportAlba() {
        var self = this;
        BaseContainer.call(self);
        // Variables
        self.generic   = generic;
        self.guard     = { authenticated: true };
        self.refresher = new Refresher();
        self.shared    = shared;

        // Handles
        self.loadStorageNodesHandle = undefined;

        var vmData = {
            storageNodes: []
        };
        ko.mapping.fromJS(vmData, viewModelMapping, self);  // Bind the data into this

        // Functions
        self.loadAlbaNodes = function() {
                var contents = '_relations';
                var options = {
                    sort: 'ip',
                    contents: contents,
                    query: JSON.stringify({  // Only fetch non-clustered nodes
                        type: 'AND',
                        items: [['storagerouter', 'EQUALS', null]]
                    })
                };
                return albaNodeService.loadAlbaNodes(options, undefined, true)
                    .then(function (data) {
                        self.update({storageNodes: data.data});
                        self.storageNodes.sort(function (node1, node2) {
                            return generic.ipSort(node1.ip(), node2.ip());
                        })
                    })
        };

        // Durandal
        self.activate = function() {
            self.refresher.init(function() {
                self.loadAlbaNodes();
            }, 5000);
            self.refresher.start();
            self.refresher.run();
        };
        self.deactivate = function() {
            self.refresher.stop();
        };
    }
    SupportAlba.prototype = $.extend({}, BaseContainer.prototype)
    return SupportAlba
});
