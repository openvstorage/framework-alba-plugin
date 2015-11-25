// Copyright 2014 iNuron NV
//
// Licensed under the Open vStorage Modified Apache License (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.openvstorage.org/license
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
    '../containers/albabackend', '../containers/albanode', '../containers/albaosd'
], function($, ko, api, shared, generic, Refresher, AlbaBackend, Node, OSD) {
    "use strict";
    return function() {
        var self = this;

        // Variables
        self.shared             = shared;
        self.guard              = { authenticated: true };
        self.refresher          = new Refresher();
        self.widgets            = [];
        self.loadBackendsHandle = undefined;
        self.loadNodesHandle    = undefined;

        // Observables
        self.loading      = ko.observable(false);
        self.nodeLoaded   = ko.observable(false);
        self.albaBackends = ko.observableArray([]);
        self.nodes        = ko.observableArray([]);
        self.disks        = ko.observableArray([]);

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
            $.each(self.nodes(), function(index, node) {
                $.each(node.disks(), function(jndex, disk) {
                    if (disk.albaBackendGuid() !== undefined) {
                        if (disk.status() === 'claimed' || disk.status() === 'unavailable') {
                            states[disk.albaBackendGuid()].claimed += 1;
                        }
                        if (disk.status() === 'error') {
                            states[disk.albaBackendGuid()].failure += 1;
                        }
                        if (disk.status() === 'warning') {
                            states[disk.albaBackendGuid()].warning += 1;
                        }
                    }
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
                        contents: '_relations'
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
                                    var albaBackend = new AlbaBackend(guid);
                                    albaBackend.load()
                                        .then(function() {
                                            albaBackend.backend().load();
                                        });
                                    return albaBackend;
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
        self.loadNodes = function() {
            if (self.albaBackends().length === 0) {
                return;
            }
            return $.Deferred(function(deferred) {
                if (generic.xhrCompleted(self.loadNodesHandle)) {
                    var options = {
                        sort: 'node_id',
                        contents: 'node_id',
                        discover: false,
                        alba_backend_guid: self.albaBackends()[0].guid()
                    };
                    self.loadNodesHandle = api.get('alba/nodes', {queryparams: options})
                        .done(function (data) {
                            var nodeIDs = [], nodes = {};
                            $.each(data.data, function (index, item) {
                                nodeIDs.push(item.node_id);
                                nodes[item.node_id] = item;
                            });
                            generic.crossFiller(
                                nodeIDs, self.nodes,
                                function(nodeID) {
                                    return new Node(nodeID, self);
                                }, 'nodeID'
                            );
                            $.each(self.nodes(), function (index, node) {
                                if ($.inArray(node.nodeID(), nodeIDs) !== -1) {
                                    node.fillData(nodes[node.nodeID()]);
                                }
                            });
                            deferred.resolve();
                        })
                        .fail(function () {
                            self.nodeLoaded(true);
                            deferred.reject();
                        });
                } else {
                    deferred.resolve();
                }
            }).promise();
        };
        self.loadOSDs = function() {
            if (self.albaBackends().length === 0) {
                return;
            }
            return self.albaBackends()[0].load()
                .then(function(data) {
                    var diskNames = [], disks = {}, changes = data.all_disks.length !== self.disks().length;
                    $.each(data.all_disks, function (index, disk) {
                        diskNames.push(disk.name);
                        disks[disk.name] = disk;
                    });
                    generic.crossFiller(
                        diskNames, self.disks,
                        function (name) {
                            return new OSD(name, self.albaBackends()[0].guid());
                        }, 'name'
                    );
                    $.each(self.disks(), function (index, disk) {
                        if ($.inArray(disk.name(), diskNames) !== -1) {
                            disk.fillData(disks[disk.name()]);
                        }
                    });
                    if (changes) {
                        self.disks.sort(function (a, b) {
                            return a.name() < b.name() ? -1 : 1;
                        });
                    }
                });
        };
        self.link = function() {
            var diskNames = [];
            $.each(self.disks(), function (index, disk) {
                diskNames.push(disk.name());
                if (disk.node === undefined) {
                    $.each(self.nodes(), function(jndex, node) {
                        if (disk.nodeID() === node.nodeID()) {
                            disk.node = node;
                            node.disks.push(disk);
                            node.disks.sort(function (a, b) {
                                return a.name() < b.name() ? -1 : 1;
                            });
                        }
                    });
                }
            });
            $.each(self.nodes(), function(jndex, node) {
                $.each(node.disks(), function(index, disk) {
                    if ($.inArray(disk.name(), diskNames) === -1) {
                        node.disks.remove(disk);
                        node.disks.sort(function (a, b) {
                            return a.name() < b.name() ? -1 : 1;
                        });
                    }
                });
            });
            self.nodeLoaded(true);
        };

        // Durandal
        self.activate = function(mode) {
            self.refresher.init(function() {
                self.load()
                    .then(self.loadNodes)
                    .then(self.loadOSDs)
                    .then(self.link);
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
