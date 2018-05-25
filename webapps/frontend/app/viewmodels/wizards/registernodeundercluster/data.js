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
define(['knockout', 'jquery',
        'viewmodels/containers/shared/base_container', 'viewmodels/services/albanode'
], function(ko, $,
            BaseContainer, albaNodeService){
    "use strict";

    var viewModelMapping = {
        'albaNodes': {
            key: function(data) {  // For relation updates: check if the GUID has changed before discarding a model
                return ko.utils.unwrapObservable(data.guid)
            }
        },
        create: function(options) {
            if (options.parent.albaBackend() === undefined) {
                return null
            }
            // This object has not yet been converted to work with ko.mapping thus manually overriden the create
            var storage_node = new AlbaNode(options.data.nodeID);
            storage_node.fillData(options.data);
            return storage_node
        }
    };
    /**
     * ViewModel constructor the registering of a node under a node cluster
     * @param albaNodeCluster: albaNodeCluster model to register the nodes under
     * @param albaNodes: All albaNodes currently known (undefined means it will retrieve all nodes itself)
     */
    function ViewModel(albaNodeCluster, albaNodes) {
        if (typeof albaNodeCluster === "undefined") {
            throw new Error('AlbaNodeCluster must be provided')
        }

        var self = this;
        BaseContainer.call(self);  // Inheritance

        var vmData = {
            'albaNodes': albaNodes || []
        };

        ko.mapping.fromJS(vmData, viewModelMapping, self);  // Bind the data into this

        // Observables
        self.albaNodeCluster = albaNodeCluster;
        self.selectedAlbaNodes = ko.observableArray([]);

        // Computed
        self.registerableAlbaNodes = ko.pureComputed(function() {
            return ko.utils.arrayFilter(self.albaNodes(), function(albaNode) {
                return ![self.albaNodeCluster.guid(), null, undefined].contains(albaNode.alba_node_cluster_guid)
            })
        });

        // Functions
        self.loadAlbaNodes = function() {
            var contents = '_relations';
            var options = {
                sort: 'storagerouter.name,storagerouter.ip,ip',
                contents: contents,
                query: JSON.stringify({  // Only fetch non-clustered nodes
                    type: 'AND',
                    items: [['alba_node_cluster', 'EQUALS', null]]
                })
            };
            return albaNodeService.loadAlbaNodes(options, undefined, true)
            .then(function (data) {
                self.update({albaNodes: data.data})
            })
        };

        // End of constructor
        self.loadAlbaNodes()
    }
    ViewModel.prototype = $.extend({}, BaseContainer.prototype);
    return ViewModel;
});
