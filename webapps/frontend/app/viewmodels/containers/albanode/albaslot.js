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

    };

    /**
     * AlbaSlot viewModel
     * @param id: ID of the slot
     * @param nodeOrCluster: AlbaNodeCluster or AlbaNode viewmodel where this model is attached too
     * @param albaBackend: albaBackend that this model is attached too
     */
    function viewModel(id, data, nodeOrCluster, albaBackend) {
        var self = this;
        BaseContainer.call(self);

        // Externally added
        self.nodeOrCluster = nodeOrCluster;
        self.albaBackend   = albaBackend;

        // Observables
        self.loaded       = ko.observable(false);
        self.osds         = ko.observableArray([]);
        self.processing   = ko.observable(false);
        self.size         = ko.observable();
        self.slotID       = ko.observable(id);
        self.status       = ko.observable();  // Can be empty, ok, warning, error
        self.statusDetail = ko.observable();
        // ASD slot properties
        self.device       = ko.observable();
        self.mountpoint   = ko.observable();
        self.usage        = ko.observable();

        var vmData = $.extend({
            osds: []
        }, data);

        ko.mapping.fromJS(vmData, viewModelMapping, self);  // Bind the data into this

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
        self.fillData = function(data) {
            self.status(data.status);
            self.statusDetail(data.status_detail || '');
            self.size(data.size);
            // ASD slot
            generic.trySet(self.usage, data, 'usage');
            generic.trySet(self.device, data, 'device');
            generic.trySet(self.mountpoint, data, 'mountpoint');
            // Add OSDs
            var osdIds = Object.keys(data.osds || {});
            generic.crossFiller(
                osdIds, self.osds,
                function(osdId) {
                    return new Osd(osdId, self, self.nodeOrCluster, self.albaBackend);
                }, 'osdID'
            );
            $.each(self.osds(), function (index, osd) {
                osd.fillData(data.osds[osd.osdID()])
            });
            self.osds.sort(function(a, b) {
                return a.osdID() < b.osdID() ? -1 : 1;
            });
            self.loaded(true);
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
    };
});
