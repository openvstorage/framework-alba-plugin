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
                    $.each(disk.asds(), function (jndex, asd) {
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
