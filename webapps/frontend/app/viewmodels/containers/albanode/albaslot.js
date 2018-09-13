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
    'ovs/generic',
    'viewmodels/containers/shared/base_container', 'viewmodels/containers/albanode/albaosd', 'viewmodels/containers/shared/albausage',
    'viewmodels/services/subscriber'
], function($, ko,
            generic,
            BaseContainer, OSD, AlbaUsage,
            subscriberService) {
    "use strict";
    var viewModelMapping = {
        'osds': {
            key: function(data) {  // For relation updates: check if the osd_id has changed before discarding a model
                return ko.utils.unwrapObservable(data.osd_id)
            },
            create: function(options) {
                var data = $.extend(options.data || {}, {
                    alba_backend_guid: ko.utils.unwrapObservable(options.parent.alba_backend_guid),
                    node_metadata: ko.utils.unwrapObservable(options.parent.node_metadata),
                    slot_id: ko.utils.unwrapObservable(options.parent.slot_id)
                });
                return new OSD(data);
            }
        },
        'usage': {
            create: function(options){
                return new AlbaUsage(options.data)
            }
        }
    };

    /**
     * AlbaSlot viewModel
     * @param data: Data to include in the model
     */
    function AlbaSlot(data) {
        var self = this;
        BaseContainer.call(self);

        // Constants
        self.errorStatuses = Object.freeze({
            warning: 'warning',
            error: 'error',
            unavailable: 'unavailable',
            unknown: 'unknown'
        });

        // Observables
        self.loaded       = ko.observable(false);
        self.processing   = ko.observable(false);
        self.size         = ko.observable();
        // ASD slot properties
        self.device       = ko.observable();
        self.mountpoint   = ko.observable();

        var vmData = $.extend({  // Order matters
            alba_backend_guid: null, // Guid of the AlbaBackend of the AlbaDetailView
            // Displaying props
            alba_backend_guids: null,
            // ASD slot props
            usage: {size: null, used: null, available: null},  // Converted into a viewModel with observables,
            device: null,
            mountpoint: null,
            aliases: null,
            available: null,
            node_id: null,
            partition_aliases: null,
            partition_amount: null,
            // OSD slot props
            status: null,
            status_detail: '',
            size: null,
            node_metadata: {}, // Can be both an object with properties or a viewModel with observable
            slot_id: null,
            osds: []
        }, data);

        ko.mapping.fromJS(vmData, viewModelMapping, self);  // Bind the data into this
        self.loaded(true);

        // Computed
        self.hasErrorStatus = ko.pureComputed(function() {
            return Object.values(self.errorStatuses).contains(self.status()) && self.status_detail() !== undefined && self.status_detail() !== ''
        });
        self.canClear = ko.pureComputed(function() {
            if (!!ko.utils.unwrapObservable(self.node_metadata.clear) === false) {
                return false;
            }
            if (self.osds().length === 0) {
                return false;
            }
            var canClear = true;
            $.each(self.osds(), function(index, osd) {
                if (osd.status() !== 'available') {
                    canClear = false;
                }
            });
            return canClear;
        });
        self.canFill = ko.pureComputed(function() {
           return !!ko.utils.unwrapObservable(self.node_metadata.fill)
        });
        self.canFillAdd = ko.pureComputed(function() {
            return !!ko.utils.unwrapObservable(self.node_metadata.fill_add)
        });
        self.canClaim = ko.pureComputed(function() {
            var claimable = false;
            $.each(self.osds(), function(index, osd) {
                if (osd.status() === 'available') {
                    claimable = true;
                }
            });
            return claimable;
        });
        self.locked = ko.pureComputed(function() {
            var locked = false;
            $.each(self.osds(), function(index, osd) {
                if (osd.locked()) {
                    locked = true;
                }
            });
            return locked;
        });

        // Event Functions
        self.addOSDs = function() {
            subscriberService.trigger('albanode_{0}:add_osds'.format([self.node_id()]), self)
        };
        self.clear = function() {
            subscriberService.trigger('albanode_{0}:clear_slot'.format([self.node_id()]), self);
        };
        self.claimOSDs = function() {
            var data = {}, osds = [];
            $.each(self.osds(), function(index, osd) {
                if (osd.status() === 'available') {
                    osds.push(osd);
                }
            });
            data[self.slot_id()] = {osds: osds};
            subscriberService.trigger('albanode_{0}:claim_osds'.format([self.node_id()]), data);
        };
    }
    // Prototypical inheritance
    AlbaSlot.prototype = $.extend({}, BaseContainer.prototype);
    return AlbaSlot
});
