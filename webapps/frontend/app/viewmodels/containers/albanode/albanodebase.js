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
    'jquery', 'knockout',
    'ovs/shared',
    'viewmodels/containers/shared/base_container'
], function($, ko,
            shared,
            BaseContainer) {
    "use strict";

    /**
     * AlbaNodeBase class
     * Acts as a parent class for albanode and albanodecluster as they share some methods
     * @constructor
     */
    function viewModel(){
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
    }
    viewModel.prototype = $.extend(BaseContainer.prototype, {  // Prototypical inheritance
        /**
         * Generate the slot relations based on the stack property
         */
        generateSlotsByStack: function(stack) {
            if (typeof stack === 'undefined') { stack = this.stack }  // No need to copy as we won't change the observable value
            if (!ko.utils.unwrapObservable(stack)) {
                throw new Error('No stack information available')
            }
            var slots = [];
            $.each(ko.utils.unwrapObservable(stack) || {}, function(slotID, slotInfo) {
                var changedSlot = $.extend({}, slotInfo);
                // Inject the slot_id back into the the slotInfo so the mapping plugin can do it's work
                changedSlot.slot_id = slotID;
                // Change the osds item to an Array so we can observe it
                var osdList = Object.keys(changedSlot.osds).map(function(osdID) {
                    changedSlot.osds[osdID].osd_id = osdID;
                    return changedSlot.osds[osdID]
                });
                changedSlot.osds = osdList;
                slots.push(changedSlot);
            });
            slots.sort(self.sortSlotsFunction);
            return slots;
        },
        /**
         * Sorts the internally stored slots. To be used as callback in sort functions
         * @param slot1: First slot to compare
         * @param slot2: Next slot to compare
         */
        sortSlotsFunction: function(slot1, slot2) {
            if ((slot1.status() === 'empty' && slot2.status() === 'empty') || (slot1.status() !== 'empty' && slot2.status() !== 'empty')) {
                    return slot1.node_id() < slot2.slot_id() ? -1 : 1;
                } else if (slot1.status() === 'empty') {  // Move empty status last
                    return 1;
                }
                return -1;
        }
    });
    return viewModel
});
