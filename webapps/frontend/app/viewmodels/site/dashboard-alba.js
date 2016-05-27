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
    'ovs/api', 'ovs/shared', 'ovs/generic', 'ovs/refresher',
    '../containers/albabackend', '../containers/albanode', '../containers/albadisk'
], function($, ko, api, shared, generic, Refresher, AlbaBackend, Node, Disk) {
    "use strict";
    return function() {
        var self = this;

        // Variables
        self.shared             = shared;
        self.guard              = { authenticated: true };
        self.refresher          = new Refresher();
        self.widgets            = [];
        self.loadBackendsHandle = undefined;

        // Observables
        self.loading      = ko.observable(false);
        self.albaBackends = ko.observableArray([]);
        self.disks        = ko.observable();

        // Computed
        self.ASDStates = ko.computed(function() {
            var states = {};
            $.each(self.albaBackends(), function(index, backend) {
                states[backend.guid()] = {
                    claimed: 0,
                    warning: 0,
                    failure: 0
                };
            });
            if (self.disks() === undefined) {
                return states;
            }
            $.each(self.disks(), function(backendGuid, disks) {
                $.each(disks(), function(index, disk) {
                    $.each(disk.osds(), function (jndex, asd) {
                        if (asd.albaBackendGuid() === backendGuid) {
                            if (asd.status() === 'claimed' || asd.status() === 'unavailable') {
                                states[backendGuid].claimed += 1;
                            }
                            if (asd.status() === 'error') {
                                states[backendGuid].failure += 1;
                            }
                            if (asd.status() === 'warning') {
                                states[backendGuid].warning += 1;
                            }
                        }
                    });
                });
            });
            return states;
        });

        // Functions
        self.load = function() {
            self.loading(true);
            return $.Deferred(function(deferred) {
                if (generic.xhrCompleted(self.loadBackendsHandle)) {
                    var options = {
                        sort: 'backend.name',
                        contents: '_relations,name'
                    };
                    self.loadBackendsHandle = api.get('alba/backends', { queryparams: options })
                        .done(function(data) {
                            var guids = [], bdata = {};
                            $.each(data.data, function(index, item) {
                                guids.push(item.guid);
                                bdata[item.guid] = item;
                            });
                            generic.crossFiller(
                                guids, self.albaBackends,
                                function(guid) {
                                    return new AlbaBackend(guid);
                                }, 'guid'
                            );
                            $.each(self.albaBackends(), function(index, albaBackend) {
                                if ($.inArray(albaBackend.guid(), guids) !== -1) {
                                    albaBackend.fillData(bdata[albaBackend.guid()]);
                                }
                            });
                            self.loading(false);
                            deferred.resolve();
                        })
                        .fail(function() {
                            self.loading(false);
                            deferred.reject();
                        });
                } else {
                    self.loading(false);
                    deferred.reject();
                }
            }).promise();
        };
        self.loadOSDs = function() {
            var allDisks = self.disks(), calls = [];
            if (allDisks === undefined) {
                allDisks = {}
            }
            if (self.albaBackends().length === 0) {
                return;
            }
            $.each(self.albaBackends(), function(index, backend) {
                calls.push(backend.load()
                    .then(function() {
                        if (backend.rawData === undefined || !backend.rawData.hasOwnProperty('storage_stack')) {
                            return true;
                        }
                        if (!allDisks.hasOwnProperty(backend.guid())) {
                            allDisks[backend.guid()] = ko.observableArray([]);
                        }
                        var diskNames = [], disks = {};
                        $.each(backend.rawData.storage_stack, function (nodeId, disksData) {
                            $.each(disksData, function (jndex, disk) {
                                diskNames.push(disk.name);
                                disks[disk.name] = disk;
                            });
                        });
                        generic.crossFiller(
                            diskNames, allDisks[backend.guid()],
                            function (name) {
                                return new Disk(name);
                            }, 'name'
                        );
                        $.each(allDisks[backend.guid()](), function (index, disk) {
                            if (diskNames.contains(disk.name())) {
                                disk.fillData(disks[disk.name()]);
                            }
                        });
                    }));
            });
            $.when.apply($, calls)
                .then(function() {
                    self.disks(allDisks);
                });
        };

        // Durandal
        self.activate = function() {
            self.refresher.init(function() {
                self.load()
                    .then(self.loadOSDs);
            }, 5000);
            self.refresher.run();
            self.refresher.start();
        };
        self.deactivate = function() {
            $.each(self.widgets, function(index, item) {
                item.deactivate();
            });
            self.refresher.stop();
        };
    };
});
