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
    'knockout',
    'ovs/generic',
    '../containers/albabackend'
], function(ko, generic, AlbaBackend) {
    "use strict";
    return function(id) {
        var self = this;

        // External injected
        self.node = undefined;
        self.disk = undefined;

        // Observables
        self.albaBackend     = ko.observable();
        self.albaBackendGuid = ko.observable();
        self.device          = ko.observable();
        self.guid            = ko.observable();
        self.highlighted     = ko.observable(false);
        self.ignoreNext      = ko.observable(false);
        self.loaded          = ko.observable(false);
        self.mountpoint      = ko.observable();
        self.nodeID          = ko.observable();
        self.osdID           = ko.observable(id);
        self.parentABGuid    = ko.observable();
        self.port            = ko.observable();
        self.processing      = ko.observable(false);
        self.status          = ko.observable();
        self.statusDetail    = ko.observable();
        self.usage           = ko.observable();

        // Computed
        self.isLocal = ko.computed(function() {
            return self.albaBackendGuid() === undefined || self.parentABGuid() === self.albaBackendGuid();
        });
        self.locked = ko.computed(function() {
            return ['nodedown', 'unknown'].contains(self.statusDetail()) || !self.isLocal();
        });
        self.marked = ko.computed(function() {
            return (self.status() === 'unavailable' || (!self.isLocal() && (self.status() === 'warning' || self.status() === 'error'))) && self.albaBackend() !== undefined;
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
                generic.trySet(self.osdID, data, 'asd_id');
                generic.trySet(self.usage, data, 'usage');
                generic.trySet(self.device, data, 'device');
                generic.trySet(self.mountpoint, data, 'mountpoint');
                generic.trySet(self.port, data, 'port');
                if (data.hasOwnProperty('alba_backend_guid') && data.alba_backend_guid !== null) {
                    self.albaBackendGuid(data.alba_backend_guid);
                } else {
                    self.albaBackendGuid(undefined);
                }
                if (self.status() === 'unavailable' || self.status() === 'error' || self.status() === 'warning') {
                    self.loadAlbaBackend();
                }
            }
            self.loaded(true);
        };

        self.claim = function() {
            var data = {};
            data[self.disk.guid()] = [self];
            self.node.claimOSDs(data)
        };
        self.remove = function() {
            self.node.removeOSD(self);
        };
        self.restart = function() {
            self.node.restartOSD(self);
        };

        self.loadAlbaBackend = function() {
            if (self.node !== undefined && self.node.parent.hasOwnProperty('otherAlbaBackendsCache')) {
                var cache = self.node.parent.otherAlbaBackendsCache(), ab;
                if (self.albaBackendGuid() !== undefined) {
                    if (!cache.hasOwnProperty(self.albaBackendGuid())) {
                        ab = new AlbaBackend(self.albaBackendGuid());
                        ab.load(false)
                            .then(function () {
                                ab.backend().load();
                            });
                        cache[self.albaBackendGuid()] = ab;
                        self.node.parent.otherAlbaBackendsCache(cache);
                    }
                    self.albaBackend(cache[self.albaBackendGuid()]);
                }
            }
        };
    };
});
