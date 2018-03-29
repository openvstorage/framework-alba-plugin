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
    'ovs/generic', 'ovs/shared',
    'viewmodels/containers/albanode/albanodebase', 'viewmodels/containers/albanode/albanode',
    'viewmodels/wizards/addosd/index', 'viewmodels/wizards/removeosd/index', 'viewmodels/wizards/registernodeundercluster/index',
    'viewmodels/services/subscriber', 'viewmodels/services/albanodecluster', 'viewmodels/services/albabackend'
], function($, app, ko, dialog,
            generic, shared,
            AlbaNodeBase, AlbaNode,
            AddOSDWizard, RemoveOSDWizard, RegisterNodeWizard,
            subscriberService, albaNodeClusterService, albaBackendService) {
    "use strict";
    var albaNodeClusterMapping = {
        // Avoid caching the same data twice in the mapping plugin. Stack is not required to be observable as we used the slot models instead
        // If stack had to be a viewmodel with observable properties: the slots would need to be created out of a copy of the stack as they now share the same instance
        // If the stack would not just be copied: the plugin would update either the stack or the slots first.
        // Since the slots is derived from the stack data (extracted data using Object.keys), the plugin will have cached the data object
        // (it pumps the full data object into the cache as a key and does a keylookup)
        // When it would update the next property, the plugin would detect that data object to apply was already applied and it won't update the object
        copy: ['stack'],
        'alba_nodes': {
            key: function(data) {  // For relation updates: check if the GUID has changed before discarding a model
                return ko.utils.unwrapObservable(data.guid)
            },
            create: function(options) {
                var data = options.data;
                var parent = options.parent;
                data.alba_node_cluster_guid = ko.utils.unwrapObservable(options.parent.guid);
                if (ko.utils.unwrapObservable(parent.stack) !== null) {
                    data.stack = generic.tryGet(ko.utils.unwrapObservable(parent.stack), data.node_id, {});
                    data.node_metadata = ko.utils.unwrapObservable(parent.cluster_metadata)
                }
                var node = new AlbaNode(data, parent.albaBackend);
                node.subscribeToSlotEvents();
                return node
            },
            update: function (options){
                var data = options.data;
                var parent = options.parent;
                data.stack = generic.tryGet(ko.utils.unwrapObservable(parent.stack), data.node_id, {});
                options.target.update(options.data);
                return options.target
            }
        }
    };
    var albaBackendDetailContext = 'albaBackendDetail';
    /**
     * AlbaNodeClusterModel class
     * @param data: Data to bind into the model. This data maps with model in the Framework
     * @param albaBackend: Possible AlbaBackend viewmodel when this model has to operate in a backend-bound context
     * @constructor
     */
    function AlbaNodeCluster(data, albaBackend){
        var self = this;

        // Inherit from base
        AlbaNodeBase.call(self);

        // Variables
        self.shared      = shared;
        self.albaBackend = albaBackend;  // Attached albaBackendModel from the parent view

        // Observables
        self.expanded          = ko.observable(false);
        self.slotsLoading      = ko.observable(false);
        self.emptySlotMessage  = ko.observable();  // When the type would be generic
        self.emptySlots        = ko.observableArray([]);

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
            alba_node_guids: [],
            slots: []
        }, data);

        ko.mapping.fromJS(vmData, albaNodeClusterMapping, self);  // Bind the data into this

        // Computed
        self.allSlots = ko.pureComputed(function() {  // Include the possible generated empty ones
            return [].concat(self.slots(), self.emptySlots())
        });
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
    }
    var functions = {
        // Functions
        /**
         * Update the current view model with the supplied data
         * Overrules the default update to pull apart stack
         * @param data: Data to update on this view model (keys map with the observables)
         * @type data: Object
         */
        update: function(data) {
            var self = this;
            if ('stack' in data) {
                // Stack is only copied so it requires special treatment
                if (!('alba_nodes' in data)) {  // Something to do as the update callback will not get fired for the alba nodes
                    data.alba_nodes = self.alba_nodes().map(function(node) {
                        return {
                            guid: node.guid(),
                            stack: generic.tryGet(ko.utils.unwrapObservable(self.stack), node.node_id(), {})
                        }
                    })
                }
            }
            return AlbaNodeBase.prototype.update.call(this, data)
        },
        /**
         * Refresh the current object instance by updating it with API data
         * @param options: Options to refresh with (Default to fetching the stack)
         * @returns {Promise}
         */
        refresh: function(options){
            if (typeof options === 'undefined') {
                options = { contents: 'stack' }
            }
            var self = this;
            return albaNodeClusterService.loadAlbaNodeCluster(self.guid(), options)
                .then(function(data) {
                    self.update(data);
                    return data
                })
        },
        deleteNode: function() {
        }
    };
    var wizards = {
        registerAlbaNode: function(){
            var self = this;
            dialog.show(new RegisterNodeWizard({
                modal: true,
                albaNodeCluster: self
            }));
        }
    };
    // Prototypical inheritance
    AlbaNodeCluster.prototype = $.extend({}, AlbaNodeBase.prototype, functions, wizards);
    return AlbaNodeCluster
});
