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
    'jquery', 'knockout', 'ovs/generic',
    './albaosd'
], function($, ko, generic, OSD) {
    "use strict";
    return function(name) {
        var self = this;

        // External injected
        self.node = undefined;

        // Observables
        self.ignoreNext   = ko.observable(false);
        self.loaded       = ko.observable(false);
        self.guid         = ko.observable();
        self.name         = ko.observable(name);
        self.nodeID       = ko.observable();
        self.osds         = ko.observableArray([]);
        self.usage        = ko.observable();
        self.status       = ko.observable();
        self.statusDetail = ko.observable();
        self.device       = ko.observable();
        self.mountpoint   = ko.observable();
        self.processing   = ko.observable(false);
        self.highlighted  = ko.observable(false);

        // Computed
        self.canRemove = ko.computed(function() {
            var onlyAvailable = true;
            $.each(self.osds(), function(index, osd) {
                if (osd.status() !== 'available') {
                    onlyAvailable = false;
                    return false;
                }
            });
            return onlyAvailable;
        });
        self.canClaim = ko.computed(function() {
            var hasAvailable = false;
            $.each(self.osds(), function(index, osd) {
                if (osd.status() === 'available') {
                    hasAvailable = true;
                    return false;
                }
            });
            return hasAvailable;
        });
        self.locked = ko.computed(function() {
            return ['nodedown', 'unknown'].contains(self.statusDetail());
        });

        // Functions
        self.fillData = function(data) {
            if (self.ignoreNext() === true) {
                self.ignoreNext(false);
            } else {
                self.status(data.status);
                self.nodeID(data.node_id);
                generic.trySet(self.guid, data, 'guid');
                generic.trySet(self.statusDetail, data, 'status_detail');
                generic.trySet(self.usage, data, 'usage');
                generic.trySet(self.device, data, 'device');
                generic.trySet(self.mountpoint, data, 'mountpoint');

                if (!data.hasOwnProperty('asds')) {
                    return;
                }
                var osdIDs = [], osds = {};
                $.each(data.asds, function (index, osd) {
                    osdIDs.push(osd.asd_id);
                    osds[osd.asd_id] = osd;
                });
                generic.crossFiller(
                    osdIDs, self.osds,
                    function (id) {
                        var osd = new OSD(id);
                        osd.disk = self;
                        return osd;
                    }, 'osdID'
                );
                $.each(self.osds(), function (index, osd) {
                    if (osdIDs.contains(osd.osdID())) {
                        osd.fillData(osds[osd.osdID()]);
                    }
                });
                self.osds.sort(function (a, b) {
                    return a.osdID() < b.osdID() ? -1 : 1;
                });
            }

            self.loaded(true);
        };

        self.initialize = function() {
            return self.node.initializeDisk(self);
        };
        self.remove = function() {
            return self.node.removeDisk(self);
        };
        self.restart = function() {
            return self.node.restartDisk(self);
        };
        self.claimOSDs = function() {
            var osds = {};
            osds[self.guid()] = [];
            $.each(self.osds(), function (index, osd) {
                if (osd.status() === 'available') {
                    osds[self.guid()].push(osd);
                }
            });
            return self.node.claimOSDs(osds);
        };
    };
});
