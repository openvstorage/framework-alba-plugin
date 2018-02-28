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
    'viewmodels/containers/shared/base_container', 'viewmodels/containers/albanode/albanode',
    'viewmodels/wizards/addosd/index', 'viewmodels/wizards/removeosd/index', 'viewmodels/wizards/registernodeundercluster/index',
    'viewmodels/services/albanodeclusterservice'
], function($, app, ko, dialog,
            generic, api, shared,
            BaseContainer, AlbaNode,
            AddOSDWizard, RemoveOSDWizard, RegisterNodeWizard,
            albaNodeClusterService) {
    "use strict";
    var albaNodeClusterMapping = {
        'alba_nodes': {
            key: function(data) {  // For relation updates: check if the GUID has changed before discarding a model
                return ko.utils.unwrapObservable(data.guid)
            },
            create: function(options) {  // This object has not yet been converted to work with ko.mapping thus manually overriden the create
                var data = options.data;
                var parent = options.parent;
                if (ko.utils.unwrapObservable(parent.stack) !== null) {data.stack = generic.tryGet(parent.stack, data.node_id, {})}
                var storage_node = new AlbaNode(data.node_id, parent.albaBackend);
                storage_node.fillData(data);
                // @todo generate osds based on stack data to fill in
                return storage_node
            }
        }
    };

    /**
     * AlbaNodeBase class
     * Acts as a parent class for albanode and albanodecluster as they share some methods
     * @constructor
     */
    function AlbaNodeClusterModel(){
        var self = this;
        // Inherit from base
        BaseContainer.call(self);

        // Variables
        self.shared      = shared;

        // Observables
        self.expanded          = ko.observable(false);
        self.slotsLoading      = ko.observable(false);
        self.emptySlotMessage  = ko.observable();  // When the type would be generic

        // Will be overriden by inheritance
        self.slots = ko.observableArray([]);
        self.stack = ko.observable({});

        ko.mapping.fromJS({}, {}, self);  // Bind the data into this


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
         * Generate the slot relations based on the stack property
         */
        self.generateSlotsByStack = function() {
            if (!ko.utils.unwrapObservable(self.stack)) {
                throw new Error('No stack information available')
            }
            var slots = [];
            $.each(ko.utils.unwrapObservable(self.stack), function(key, value) {

            });
                        // Add slots
            var slotIDs = Object.keys(generic.tryGet(data, 'stack', {}));
            var emptySlotID = undefined;
            if (self.type() === 'GENERIC') {
                if (self.slots().length > 0){
                    $.each(self.slots().slice(), function(index, slot) {
                       if (slot.status() === 'empty' && !slotIDs.contains(slot.slotID())){
                           // Empty slot found in the model of the GUI, let's add it to the stack output
                           // This way the crossfiller won't remove it
                           emptySlotID = slot.slotID();
                           slotIDs.push(emptySlotID);
                           return false;  // Break
                       }
                    });
                }
            }
            generic.crossFiller(
                slotIDs, self.slots,
                function(slotID) {
                    return new Slot(slotID, self, self.albaBackend);
                }, 'slotID'
            );
            $.each(self.slots(), function (index, slot) {
                if (slot.slotID() === emptySlotID) {
                    // Skip filling the data for the new slot. There is no stack data for it
                    return true;
                }
                slot.fillData(data.stack[slot.slotID()])
            });
            // No empty slot found, generate one for the future refresh runs
            if (emptySlotID === undefined && self.type() === 'GENERIC') {
                self.generateEmptySlot();
            }
            self.slots.sort(function(a, b) {
                if ((a.status() === 'empty' && b.status() === 'empty') || (a.status() !== 'empty' && b.status() !== 'empty')) {
                    return a.slotID() < b.slotID() ? -1 : 1;
                } else if (a.status() === 'empty') {  // Move empty status last
                    return 1;
                }
                return -1;
            });
            self.slotsLoading(false);
        }

    }
    return AlbaNodeClusterModel
});
