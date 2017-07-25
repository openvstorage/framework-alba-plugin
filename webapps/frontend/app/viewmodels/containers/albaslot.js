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
    '../containers/albaosd'
], function($, ko, generic, Osd) {
    "use strict";
    return function(id, node, albaBackend) {
        var self = this;

        // Externally added
        self.node        = node;
        self.albaBackend = albaBackend;

        // Observables
        self.loaded          = ko.observable(false);
        self.osds            = ko.observableArray([]);
        self.slotId          = ko.observable(id);
        self.status          = ko.observable();  // Can be empty, ok, warning ,error
        self.statusDetail    = ko.observable();
        self.size            = ko.observable();
        self.processing      = ko.observable(false);

        // Computed
        self.canClear = ko.computed(function() {
            if (self.node !== undefined && self.node.nodeMetadata() !== undefined &&
                self.node.nodeMetadata[self.slotId()] !== undefined &&
                self.node.nodeMetadata[self.slotId()].slots.clear === false) {
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
        self.canFill = ko.computed(function() {
           return self.node.nodeMetadata().slots.fill
        });
        self.canFillAdd = ko.computed(function() {
            return self.node.nodeMetadata().slots.fill_add
        });
        self.canClaim = ko.computed(function() {
            var claimable = false;
            $.each(self.osds(), function(index, osd) {
                if (osd.status() === 'available') {
                    claimable = true;
                }
            });
            return claimable;
        });
        self.processing = ko.computed(function() {
            var processing = false;
            $.each(self.osds(), function(index, osd) {
                if (osd.processing()) {
                    processing = true;
                }
            });
            return processing;
        });
        self.locked = ko.computed(function() {
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
            alert('Hhoooosh... And it\'s gone.');
        };
        self.fillData = function(data) {
            self.status(data.status);
            self.statusDetail(data.status_detail || '');
            self.size(data.size);
            // Add osds
            var osdIds = Object.keys(data.osds || {});
            generic.crossFiller(
                osdIds, self.osds,
                function(osdId) {
                    return new Osd(osdId, self, self.node, self.albaBackend);
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
            data[self.slotId()] = osds;
            self.node.claimOSDs(data, self.node.guid());
        };
    };
});
