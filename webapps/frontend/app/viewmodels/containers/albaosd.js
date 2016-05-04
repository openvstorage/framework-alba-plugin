// Copyright 2016 iNuron NV
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
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
        self.ignoreNext      = ko.observable(false);
        self.loaded          = ko.observable(false);
        self.nodeID          = ko.observable();
        self.guid            = ko.observable();
        self.asdID           = ko.observable(id);
        self.usage           = ko.observable();
        self.status          = ko.observable();
        self.statusDetail    = ko.observable();
        self.device          = ko.observable();
        self.mountpoint      = ko.observable();
        self.port            = ko.observable();
        self.processing      = ko.observable(false);
        self.albaBackend     = ko.observable();
        self.albaBackendGuid = ko.observable();
        self.parentABGuid    = ko.observable();
        self.highlighted     = ko.observable(false);

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
                generic.trySet(self.asdID, data, 'asd_id');
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
                        ab.load()
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
