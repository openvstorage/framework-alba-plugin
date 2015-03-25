// Copyright 2014 CloudFounders NV
// All rights reserved
/*global define */
define([
    'knockout',
    'ovs/generic',
    '../containers/albabackend'
], function(ko, generic, AlbaBackend) {
    "use strict";
    return function(name, albaBackendGuid) {
        var self = this;

        // External injected
        self.node = undefined;

        // Observables
        self.ignoreNext      = ko.observable(false);
        self.loaded          = ko.observable(false);
        self.name            = ko.observable(name);
        self.boxID           = ko.observable();
        self.asdID           = ko.observable();
        self.statistics      = ko.observable();
        self.status          = ko.observable();
        self.statusDetail    = ko.observable();
        self.device          = ko.observable();
        self.mountpoint      = ko.observable();
        self.port            = ko.observable();
        self.processing      = ko.observable(false);
        self.albaBackend     = ko.observable();
        self.albaBackendGuid = ko.observable();
        self.parentABGuid    = ko.observable(albaBackendGuid);

        // Computed
        self.isLocal = ko.computed(function() {
            return self.albaBackendGuid() === undefined || (self.parentABGuid() !== undefined && self.parentABGuid() === self.albaBackendGuid());
        });

        // Functions
        self.fillData = function(data) {
            if (self.ignoreNext() === true) {
                self.ignoreNext(false);
            } else {
                self.status(data.status);
                self.boxID(data.box_id);
                generic.trySet(self.statusDetail, data, 'status_detail');
                generic.trySet(self.albaBackendGuid, data, 'alba_backend_guid');
                generic.trySet(self.asdID, data, 'asd_id');
                generic.trySet(self.statistics, data, 'statistics');
                generic.trySet(self.device, data, 'device');
                generic.trySet(self.mountpoint, data, 'mountpoint');
                generic.trySet(self.port, data, 'port');
                if (self.status() === 'unavailable' || self.status() === 'error' || self.status() === 'warning') {
                    self.loadAlbaBackend();
                }
            }

            self.loaded(true);
        };
        self.initialize = function() {
            self.processing(true);
            self.node.initializeNode(self.name())
                .done(function() {
                    self.ignoreNext(true);
                    self.status('initialized');
                })
                .always(function() {
                    self.processing(false);
                });
        };
        self.remove = function() {
            self.processing(true);
            self.node.removeNode(self.name())
                .done(function() {
                    self.ignoreNext(true);
                    self.status('uninitialized');
                })
                .always(function() {
                    self.processing(false);
                });
        };
        self.claim = function() {
            var osds = {};
            osds[self.asdID()] = self.node.guid();
            self.processing(true);
            self.node.claimOSD(osds, self.name())
                .done(function() {
                    self.ignoreNext(true);
                    self.status('claimed');
                })
                .always(function() {
                    self.processing(false);
                });
        };
        self.restart = function() {
            self.processing(true);
            self.node.restartOSD(self.name())
                .always(function() {
                    self.processing(false);
                });
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
