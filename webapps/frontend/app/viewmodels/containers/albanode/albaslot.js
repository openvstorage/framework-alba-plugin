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
    'viewmodels/containers/shared/base_container', 'viewmodels/containers/albanode/albaosd'
], function($, ko, generic, BaseContainer, Osd) {
    "use strict";
    var viewModelMapping = {
        'osds': {
            key: function(data) {  // For relation updates: check if the osd_id has changed before discarding a model
                return ko.utils.unwrapObservable(data.osd_id)
            },
            create: function(options) {
                var data = $.extend(options.data || {}, {
                    alba_backend_guid: ko.utils.unwrapObservable(options.parent.alba_backend_guid)
                });
                return new Osd(data);
            }
        }
    };

    /**
     * AlbaSlot viewModel
     * @param data: Data to include in the model
     * @param nodeOrCluster: AlbaNodeCluster or AlbaNode viewmodel where this model is attached too
     * @param albaBackend: albaBackend that this model is attached too
     */
    function viewModel(data, nodeOrCluster, albaBackend) {
        var self = this;
        BaseContainer.call(self);

        // Externally added
        self.nodeOrCluster = nodeOrCluster;
        self.albaBackend   = albaBackend;

        // Observables
        self.loaded       = ko.observable(false);
        self.processing   = ko.observable(false);
        self.size         = ko.observable();
        // ASD slot properties
        self.device       = ko.observable();
        self.mountpoint   = ko.observable();
        self.usage        = ko.observable();

        var vmData = $.extend({
            // Displaying props
            alba_backend_guids: null,
            // ASD slot props
            usage: null,
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
            osds: [],
            metadata: {} // @Todo should this be a viewModel with observables?
        }, data);

        ko.mapping.fromJS(vmData, viewModelMapping, self);  // Bind the data into this
        self.loaded(true);

        // Computed
        self.canClear = ko.computed(function() {
            if (self.nodeOrCluster !== undefined && self.nodeOrCluster.metadata() !== undefined && self.nodeOrCluster.metadata().clear === false) {
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
           return self.nodeOrCluster.metadata().fill
        });
        self.canFillAdd = ko.pureComputed(function() {
            return self.nodeOrCluster.metadata().fill_add
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

        // Functions
        self.clear = function() {
            self.nodeOrCluster.removeSlot(self);
        };
        self.claimOSDs = function() {
            var data = {}, osds = [];
            $.each(self.osds(), function(index, osd) {
                if (osd.status() === 'available') {
                    osds.push(osd);
                }
            });
            data[self.slotID()] = {slot: self, osds: osds};
            self.nodeOrCluster.claimOSDs(data);
        };
    }
    return viewModel
});
