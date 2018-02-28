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
    'durandal/app', 'knockout', 'jquery',
    'ovs/generic'
], function(app, ko, $, generic) {
    "use strict";
    return function(id, slot, nodeOrCluster, parentAlbaBackend) {
        var self = this;

        // variables
        self.errorStatuses = ['warning', 'error', 'unavailable', 'unknown'];

        // External injected
        self.nodeOrCluster = nodeOrCluster;
        self.slot = slot;
        self.disk = undefined;

        // Observables
        self.albaBackendGuid = ko.observable();
        self.device          = ko.observable();
        self.guid            = ko.observable();
        self.ignoreNext      = ko.observable(false);
        self.ips             = ko.observableArray([]);
        self.loaded          = ko.observable(false);
        self.mountpoint      = ko.observable();
        self.nodeID          = ko.observable();
        self.osdID           = ko.observable(id);
        self.parentABGuid    = ko.observable(parentAlbaBackend.guid());
        self.port            = ko.observable().extend({numeric: {min: 1, max: 65535}});
        self.processing      = ko.observable(false);
        self.slotID          = ko.observable();
        self._status         = ko.observable();  // can be ok, warning, error, unavailable, unknown
        self.statusDetail    = ko.observable();
        self.type            = ko.observable();
        self.usage           = ko.observable();

        // Computed
        self.status = ko.pureComputed(function() {
            if (self.errorStatuses.contains(self._status())) {
                return self._status();
            }
            if ([null, undefined].contains(self.albaBackendGuid())) {
                return 'available';
            }
            return self.albaBackendGuid() === self.parentABGuid() ? 'claimed' : 'unavailable';
        });
        self.isLocal = ko.pureComputed(function() {
            return [null, undefined].contains(self.albaBackendGuid()) || self.parentABGuid() === self.albaBackendGuid();
        });
        self.locked = ko.pureComputed(function() {
            return ['nodedown', 'unknown'].contains(self.statusDetail()) || !self.isLocal();
        });
        self.marked = ko.pureComputed(function() {
            return (self.status() === 'unavailable' || (!self.isLocal() && (self.status() === 'warning' || self.status() === 'error'))) && self.albaBackend() !== undefined;
        });
        self.sockets = ko.pureComputed(function() {
            var sockets = [];
            $.each(self.ips(), function(index, ip) {
               sockets.push(ip + ":" + self.port())
            });
            return sockets
        });

        // Functions
        self.fillData = function(data) {
            if (self.ignoreNext() === true) {
                self.ignoreNext(false);
            } else {
                self._status(data.status);
                self.nodeID(data.node_id);
                if (self.slot !== undefined) {
                    self.slotID(self.slot.slotID());
                }
                generic.trySet(self.guid, data, 'guid');
                generic.trySet(self.statusDetail, data, 'status_detail');
                generic.trySet(self.osdID, data, 'asd_id');
                generic.trySet(self.usage, data, 'usage');
                generic.trySet(self.device, data, 'device');
                generic.trySet(self.mountpoint, data, 'mountpoint');
                generic.trySet(self.port, data, 'port');
                generic.trySet(self.ips, data, 'ips');
                generic.trySet(self.type, data, 'type');
                generic.trySet(self.albaBackendGuid, data, 'claimed_by');
                if (['unavailable', 'error', 'warning'].contains(self.status())) {
                    if (self.albaBackendGuid() !== undefined && self.albaBackendGuid() !== 'unknown') {
                        // Fire an event so the backend page would load the AlbaBackend associated with this osd
                        app.trigger('alba_backend:load', self.albaBackendGuid())
                    }
                }
            }
            self.loaded(true);
        };

        // Functions
        self.claim = function() {
            var data = {};
            data[self.slotID()] = {slot: self.slot, osds: [self]};
            self.nodeOrCluster.claimOSDs(data);
        };
        self.remove = function() {
            self.nodeOrCluster.removeOSD(self);
        };
        self.restart = function() {
            self.nodeOrCluster.restartOSD(self);
        };
    };
});
