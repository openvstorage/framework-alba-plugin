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
    'jquery', 'durandal/app', 'knockout', 'plugins/router', 'plugins/dialog',
    'ovs/shared', 'ovs/generic', 'ovs/refresher', 'ovs/api',
    '../containers/backend', '../containers/backendtype', '../containers/albabackend', '../containers/albanode', '../containers/albadisk', '../containers/storagerouter', '../containers/vpool',
    '../wizards/addpreset/index', '../wizards/linkbackend/index'
], function($, app, ko, router, dialog,
            shared, generic, Refresher, api,
            Backend, BackendType, AlbaBackend, Node, Disk, StorageRouter, VPool,
            AddPresetWizard, LinkBackendWizard) {
    "use strict";
    return function() {
        var self = this;

        // Variables
        self.shared             = shared;
        self.generic            = generic;
        self.guard              = { authenticated: true };
        self.refresher          = new Refresher();
        self.widgets            = [];
        self.initializing       = false;
        self.nodesHandle        = {};
        self.storageRouterCache = {};
        self.initialRun         = true;

        // Observables
        self.albaBackend            = ko.observable();
        self.backend                = ko.observable();
        self.discoveredNodes        = ko.observableArray([]);
        self.disks                  = ko.observableArray([]);
        self.dNodesLoading          = ko.observable(false);
        self.otherAlbaBackendsCache = ko.observable({});
        self.registeredNodes        = ko.observableArray([]);
        self.registeredNodesNodeIDs = ko.observableArray([]);
        self.rNodesLoading          = ko.observable(true);
        self.vPools                 = ko.observableArray([]);

        // Computed
        self.filteredDiscoveredNodes = ko.computed(function() {
            var nodes = [];
            $.each(self.discoveredNodes(), function(index, node) {
                if (!self.registeredNodesNodeIDs().contains(node.nodeID())) {
                    nodes.push(node);
                }
            });
            return nodes;
        });
        self.expanded = ko.computed({
            write: function(value) {
                $.each(self.registeredNodes(), function(index, node) {
                    node.expanded(value);
                });
            },
            read: function() {
                var expanded = false;
                $.each(self.registeredNodes(), function(index, node) {
                    expanded |= node.expanded();  // Bitwise or, |= is correct.
                });
                return expanded;
            }
        });
        self.otherAlbaBackends = ko.computed(function() {
            var albaBackends = [], cache = self.otherAlbaBackendsCache(), counter = 0;
            $.each(cache, function(index, albaBackend) {
                if (albaBackend.guid() !== self.albaBackend().guid()) {
                    albaBackend.color(generic.getColor(counter));
                    albaBackends.push(albaBackend);
                    counter += 1;
                }
            });
            return albaBackends;
        });
        self.ASDStates = ko.computed(function() {
            var states = {
                claimed: 0,
                warning: 0,
                failure: 0
            };
            if (self.albaBackend() !== undefined) {
                $.each(self.registeredNodes(), function (index, node) {
                    $.each(node.disks(), function (jndex, disk) {
                        $.each(disk.osds(), function(kndex, asd) {
                            if (asd.albaBackendGuid() === self.albaBackend().guid()) {
                                if (asd.status() === 'claimed') {
                                    states.claimed += 1;
                                }
                                if (asd.status() === 'error') {
                                    states.failure += 1;
                                }
                                if (asd.status() === 'warning') {
                                    states.warning += 1;
                                }
                            }
                        });
                    });
                });
            }
            return states;
        });
        self.showDetails = ko.computed(function() {
            return self.albaBackend() !== undefined && self.backend() !== undefined;
        });
        self.showActions = ko.computed(function() {
            return self.showDetails() && !['installing', 'new'].contains(self.backend().status());
        });

        // Functions
        self.refresh = function() {
            self.dNodesLoading(true);
            self.fetchNodes(true);
        };
        self.linkBackend = function() {
            if (self.albaBackend().successfullyLoaded() === false) {
                return;
            }
            dialog.show(new LinkBackendWizard (
                { modal: true,
                  albaBackend: self.albaBackend() }
            ));
        };
        self.load = function() {
            return $.Deferred(function (deferred) {
                var backend = self.backend(), backendType;
                backend.load()
                    .then(function(backendData) {
                        return $.Deferred(function(subDeferred) {
                            if (backend.backendType() === undefined) {
                                backendType = new BackendType(backend.backendTypeGuid());
                                backendType.load();
                                backend.backendType(backendType);
                            }
                            if (backendData.hasOwnProperty('alba_backend_guid') && backendData.alba_backend_guid !== null) {
                                if (self.albaBackend() === undefined) {
                                    var albaBackend = new AlbaBackend(backendData.alba_backend_guid);
                                    albaBackend.vPools = self.vPools;
                                    self.albaBackend(albaBackend);
                                }
                                subDeferred.resolve(self.albaBackend());
                            } else {
                                if (!self.initializing) {
                                    self.initializing = true;
                                    api.post('alba/backends', {
                                        data: {
                                            scaling: 'LOCAL',
                                            backend_guid: self.backend().guid()
                                        }
                                    })
                                        .fail(function() {
                                            self.initializing = false;
                                        });
                                }
                                subDeferred.reject();
                            }
                        }).promise();
                    })
                    .then(function(albaBackend) {
                        return albaBackend.load(!self.initialRun)
                            .then(albaBackend.getAvailableActions);
                    })
                    .done(deferred.resolve)
                    .fail(deferred.reject);
            }).promise();
        };
        self.formatBytes = function(value) {
            return generic.formatBytes(value);
        };
        self.formatPercentage = function(value) {
            if (isNaN(value)) {
                return "0 %";
            } else {
                return generic.formatPercentage(value);
            }
        };
        self.loadVPools = function() {
            return $.Deferred(function(deferred) {
                if (generic.xhrCompleted(self.vPoolsHandle)) {
                    var options = {
                        sort: 'name',
                        contents: ''
                    };
                    self.vPoolsHandle = api.get('vpools', { queryparams: options })
                        .then(function(data) {
                            var guids = [], vpdata = {};
                            $.each(data.data, function (index, vpool) {
                                guids.push(vpool.guid);
                                vpdata[vpool.guid] = vpool;
                            });
                            generic.crossFiller(
                                guids, self.vPools,
                                function (guid) {
                                    return new VPool(guid);
                                }, 'guid'
                            );
                            $.each(self.vPools(), function (index, vpool) {
                                if ($.inArray(vpool.guid(), guids) !== -1) {
                                    vpool.fillData(vpdata[vpool.guid()]);
                                }
                            });
                        })
                        .always(deferred.resolve);
                } else {
                    deferred.resolve();
                }
            }).promise();
        };
        self.fetchNodes = function(discover) {
            if (discover === undefined) {
                discover = false;
            }
            discover = !!discover;
            if (self.albaBackend() === undefined) {
                return;
            }
            return $.Deferred(function(deferred) {
                if (generic.xhrCompleted(self.nodesHandle[discover])) {
                    var options = {
                        sort: 'ip',
                        contents: 'node_id,_relations' + (discover ? ',_dynamics' : ''),
                        discover: discover
                    };
                    if (self.albaBackend() !== undefined) {
                        self.nodesHandle[discover] = api.get('alba/nodes', {queryparams: options})
                            .done(function (data) {
                                var nodeIDs = [], nodes = {}, oArray = discover ? self.discoveredNodes : self.registeredNodes;
                                $.each(data.data, function (index, item) {
                                    nodeIDs.push(item.node_id);
                                    nodes[item.node_id] = item;
                                });
                                if (!discover) {
                                    self.registeredNodesNodeIDs(nodeIDs);
                                }
                                generic.crossFiller(
                                    nodeIDs, oArray,
                                    function(nodeID) {
                                        var node = new Node(nodeID, self.albaBackend(), self);
                                        node.disksLoading(true);
                                        return node;
                                    }, 'nodeID'
                                );
                                $.each(oArray(), function (index, node) {
                                    if ($.inArray(node.nodeID(), nodeIDs) !== -1) {
                                        node.fillData(nodes[node.nodeID()]);
                                        var sr, storageRouterGuid = node.storageRouterGuid();
                                        if (storageRouterGuid && (node.storageRouter() === undefined || node.storageRouter().guid() !== storageRouterGuid)) {
                                            if (!self.storageRouterCache.hasOwnProperty(storageRouterGuid)) {
                                                sr = new StorageRouter(storageRouterGuid);
                                                sr.load();
                                                self.storageRouterCache[storageRouterGuid] = sr;
                                            }
                                            node.storageRouter(self.storageRouterCache[storageRouterGuid]);
                                        }
                                    }
                                });
                                if (discover) {
                                    self.dNodesLoading(false);
                                } else {
                                    self.rNodesLoading(false);
                                }
                                deferred.resolve();
                            })
                            .fail(function () {
                                deferred.reject();
                            });
                    }
                } else {
                    deferred.resolve();
                }
            }).promise();
        };
        self.loadOSDs = function() {
            var data = self.albaBackend().rawData;
            if (data === undefined || !data.hasOwnProperty('storage_stack')) {
                return;
            }
            var diskNames = [], disks = {}, changes = data.storage_stack.local.length !== self.disks().length,
                diskNode = {}, nodeDisks = {};
            $.each(data.storage_stack.local, function (nodeId, disksData) {
                $.each(disksData, function(index, disk) {
                    diskNames.push(disk.name);
                    disks[disk.name] = disk;
                    diskNode[disk.name] = nodeId;
                });
            });
            generic.crossFiller(
                diskNames, self.disks,
                function (name) {
                    return new Disk(name);
                }, 'name'
            );
            $.each(self.disks(), function (index, disk) {
                if ($.inArray(disk.name(), diskNames) !== -1) {
                    disk.fillData(disks[disk.name()]);
                }
                var nodeId = diskNode[disk.name()];
                if (!nodeDisks.hasOwnProperty(nodeId)) {
                    nodeDisks[nodeId] = [];
                }
                nodeDisks[nodeId].push(disk);
            });
            if (changes) {
                self.disks.sort(function (a, b) {
                    return a.name() < b.name() ? -1 : 1;
                });
                $.each(self.registeredNodes(), function(index, node) {
                    if (!nodeDisks.hasOwnProperty(node.nodeID())) {
                        node.disks([]);
                    } else {
                        node.disks(nodeDisks[node.nodeID()]);
                    }
                    node.disks.sort(function (a, b) {
                        return a.name() < b.name() ? -1 : 1;
                    });
                    node.disksLoading(self.initialRun);
                    $.each(node.disks(), function(index, disk) {
                        disk.node = node;
                        $.each(disk.osds(), function(_, asd) {
                            asd.node = node;
                            asd.parentABGuid(self.albaBackend().guid());
                        })
                    })
                })
            }
        };
        self.removeBackend = function() {
            return $.Deferred(function(deferred) {
                if (self.albaBackend() === undefined || !self.albaBackend().availableActions().contains('REMOVE')) {
                    deferred.reject();
                    return;
                }
                app.showMessage(
                    $.t('alba:detail.delete.warning'),
                    $.t('ovs:generic.areyousure'),
                    [$.t('ovs:generic.yes'), $.t('ovs:generic.no')]
                )
                    .done(function(answer) {
                        if (answer === $.t('ovs:generic.yes')) {
                            generic.alertSuccess(
                                $.t('alba:detail.delete.started'),
                                $.t('alba:detail.delete.msgstarted')
                            );
                            router.navigate(self.shared.routing.loadHash('backends'));
                            api.del('alba/backends/' + self.albaBackend().guid())
                                .then(self.shared.tasks.wait)
                                .done(function() {
                                    generic.alertSuccess(
                                        $.t('alba:detail.delete.complete'),
                                        $.t('alba:detail.delete.success')
                                    );
                                    deferred.resolve();
                                })
                                .fail(function(error) {
                                    generic.alertError(
                                        $.t('ovs:generic.error'),
                                        $.t('alba:detail.delete.failed', { why: error })
                                    );
                                    deferred.reject();
                                });
                        } else {
                            deferred.reject();
                        }
                    });
            }).promise();
        };
        self.removePreset = function(name) {
            return $.Deferred(function(deferred) {
                app.showMessage(
                    $.t('alba:presets.delete.warning', { what: name }),
                    $.t('ovs:generic.areyousure'),
                    [$.t('ovs:generic.yes'), $.t('ovs:generic.no')]
                )
                    .done(function(answer) {
                        if (answer === $.t('ovs:generic.yes')) {
                            generic.alertSuccess(
                                $.t('alba:presets.delete.started'),
                                $.t('alba:presets.delete.msgstarted')
                            );
                            api.post('alba/backends/' + self.albaBackend().guid() + '/delete_preset', { data: { name: name } })
                                .then(self.shared.tasks.wait)
                                .done(function() {
                                    generic.alertSuccess(
                                        $.t('alba:presets.delete.complete'),
                                        $.t('alba:presets.delete.success')
                                    );
                                    deferred.resolve();
                                })
                                .fail(function(error) {
                                    generic.alertError(
                                        $.t('ovs:generic.error'),
                                        $.t('alba:presets.delete.failed', { why: error })
                                    );
                                    deferred.reject();
                                });
                        } else {
                            deferred.reject();
                        }
                    });
            }).promise();
        };
        self.addPreset = function() {
            dialog.show(new AddPresetWizard({
                modal: true,
                backend: self.albaBackend(),
                currentPresets: self.albaBackend().enhancedPresets(),
                editPreset: false
            }));
        };
        self.editPreset = function(data) {
            dialog.show(new AddPresetWizard({
                modal: true,
                currentPreset: data,
                backend: self.albaBackend(),
                currentPresets: self.albaBackend().enhancedPresets(),
                editPreset: true
            }));
        };

        // Durandal
        self.activate = function(mode, guid) {
            self.backend(new Backend(guid));
            self.refresher.init(function() {
                self.loadVPools();
                return self.load()
                    .then(self.fetchNodes)
                    .then(self.loadOSDs)
                    .then(function() {
                        if (self.initialRun === true) {
                            self.initialRun = false;
                            self.refresher.skipPause = true;
                        }
                    })
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
