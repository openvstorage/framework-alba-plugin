// Copyright 2015 CloudFounders NV
// All rights reserved
/*global define */
define([
    'jquery', 'knockout',
    'ovs/api', 'ovs/shared', 'ovs/generic', 'ovs/refresher',
    '../containers/albabackend', '../containers/albanode'
], function($, ko, api, shared, generic, Refresher, AlbaBackend, Node) {
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
                        sort: 'box_id',
                        contents: 'box_id',
                        discover: false,
                        alba_backend_guid: self.albaBackends()[0].guid()
                    };
                    self.loadNodesHandle = api.get('alba/nodes', {queryparams: options})
                        .done(function (data) {
                            var nodeIDs = [], nodes = {};
                            $.each(data.data, function (index, item) {
                                nodeIDs.push(item.box_id);
                                nodes[item.box_id] = item;
                            });
                            generic.crossFiller(
                                nodeIDs, self.nodes,
                                function(boxID) {
                                    return new Node(boxID, undefined, self);
                                }, 'boxID'
                            );
                            $.each(self.nodes(), function (index, node) {
                                if ($.inArray(node.boxID(), nodeIDs) !== -1) {
                                    node.fillData(nodes[node.boxID()]);
                                }
                            });
                            self.nodeLoaded(true);
                        })
                        .fail(function () {
                            self.nodeLoaded(true);
                            deferred.reject();
                        });
                } else {
                    self.nodeLoaded(true);
                    deferred.resolve();
                }
            }).promise();
        };

        // Durandal
        self.activate = function(mode) {
            self.refresher.init(function() {
                self.load()
                    .then(self.loadNodes);
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
