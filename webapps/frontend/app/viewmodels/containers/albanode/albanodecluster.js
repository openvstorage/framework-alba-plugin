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
    'jquery', 'durandal/app', 'knockout', 'plugins/dialog',
    'ovs/generic', 'ovs/api', 'ovs/shared',
    'viewmodels/containers/shared/base_container', 'viewmodels/containers/albanode/albaslot',
    'viewmodels/wizards/addosd/index', 'viewmodels/wizards/removeosd/index',
    'viewmodels/services/albanodeclusterservice'
], function($, app, ko, dialog,
            generic, api, shared,
            BaseContainer, Slot,
            AddOSDWizard, RemoveOSDWizard,
            albaNodeClusterService) {
    "use strict";
    var albaNodeClusterMapping = {
        'alba_nodes': {
            key: function(data) {  // For relation updates: check if the GUID has changed before discarding a model
                return ko.utils.unwrapObservable(data.guid)
            },
            create: function(options) {  // This object has not yet been converted to work with ko.mapping thus manually overriden the create
                var nodeID = options.data.nodeID;
                var storage_node = new AlbaNode(nodeID);
                storage_node.fillData(options.data);
                return storage_node
            }
        }
    };

    /**
     * AlbaNodeClusterModel class
     * @param data: Data to bind into the model. This data maps with model in the Framework
     * @constructor
     */
    function AlbaNodeClusterModel(data){
        var self = this;

        // Inherit from base
        BaseContainer.call(self);

        // Variables
        self.shared      = shared;

        // Observables
        self.expanded          = ko.observable(false);

        // Default data - replaces fillData - this always creates observables for the passed keys
        // Most of these properties are given by the API but setting them explicitly to have a view of how this model looks
        var vmData = $.extend({
            guid: null,
            name: null,
            ips: [],
            cluster_metadata: null,
            local_summary: null,
            stack: null,
            maintenance_services: [],
            supported_osd_types: [],
            read_only_mode: true,
            alba_nodes: [],
            alba_node_guids: []
        }, data);

        ko.mapping.fromJS(vmData, albaNodeClusterMapping, self);  // Bind the data into this


        // Computed
        self.canInitializeAll = ko.computed(function() {
            // @Todo implement
            return true;
        });
        self.canClaimAll = ko.computed(function() {
            // @Todo implement
            return true;
        });
        self.canDelete = ko.computed(function() {
            // @Todo implement
            return true;
        });

        // Functions
        /**
         * Refresh the current object instance by updating it with API data
         * @param queryParams: Additional query params. Defaults to no params
         * @param relayParams: Relay to use (Optional, defaults to no relay)
         * @returns {Deferred}
         */
        self.refresh = function(queryParams, relayParams){
            return albaNodeClusterService.loadAlbaNodeCluster(self.guid(), queryParams, relayParams)
                .done(function(data) {
                    self.update(data.data)
                })
                .fail(function(data) {
                    // @TODO remove
                    console.log('Failed to update current object: {0}'.format([data]))
                })
        };
        // Functions
        self.localSummaryByBackend = function(albaBackendGuid){
          // Returns a computed to get notified about all changes to the localSummary here
          return ko.computed(function() {
              // @Todo implement
              return {};
          })
        };

    }
    return AlbaNodeClusterModel
});
