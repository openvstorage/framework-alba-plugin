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
    'jquery', 'durandal/app', 'knockout', 'plugins/router', 'plugins/dialog',
    'ovs/shared', 'ovs/generic', 'ovs/refresher', 'ovs/api',
    '../containers/backend', '../containers/backendtype', '../containers/albabackend',
    '../containers/albanode', '../containers/albaosd', '../containers/storagerouter', '../containers/vpool',
    '../wizards/addpreset/index'
], function($, app, ko, router, dialog, shared, generic, Refresher, api, Backend, BackendType, AlbaBackend,
            Node, OSD, StorageRouter, VPool, AddPresetWizard) {
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
        self.backend                = ko.observable();
        self.albaBackend            = ko.observable();
        self.rNodesLoading          = ko.observable(true);
        self.dNodesLoading          = ko.observable(false);
        self.registeredNodes        = ko.observableArray([]);
        self.registeredNodesNodeIDs = ko.observableArray([]);
        self.discoveredNodes        = ko.observableArray([]);
        self.disks                  = ko.observableArray([]);
        self.vPools                 = ko.observableArray([]);
        self.otherAlbaBackendsCache = ko.observable({});

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
                        if (disk.albaBackendGuid() === self.albaBackend().guid()) {
                            if (disk.status() === 'claimed') {
                                states.claimed += 1;
                            }
                            if (disk.status() === 'error') {
                                states.failure += 1;
                            }
                            if (disk.status() === 'warning') {
                                states.warning += 1;
                            }
                        }
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
                            .then(function(data) {
                                albaBackend.getAvailableActions();
                                return data;
                            });
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
                                        var node = new Node(nodeID, self);
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
        self.loadOSDs = function(data) {
            if (!data.hasOwnProperty('all_disks')) {
                return;
            }
            var diskNames = [], disks = {}, changes = data.all_disks.length !== self.disks().length;
            $.each(data.all_disks, function (index, disk) {
                diskNames.push(disk.name);
                disks[disk.name] = disk;
            });
            generic.crossFiller(
                diskNames, self.disks,
                function (name) {
                    return new OSD(name, self.albaBackend().guid());
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
        };
        self.link = function() {
            var diskNames = [], nodeDisks = {};
            $.each(self.registeredNodes(), function(index, node) {
                nodeDisks[node.nodeID()] = {
                    node: node,
                    disks: node.disks(),
                    names: node.diskNames(),
                    changed: false
                };
            });
            $.each(self.disks(), function (index, disk) {
                diskNames.push(disk.name());
                if (disk.node === undefined) {
                    $.each(nodeDisks, function(nodeID, nodeInfo) {
                        if (disk.nodeID() === nodeID && !nodeInfo.names.contains(disk.name())) {
                            disk.node = nodeInfo.node;
                            nodeInfo.disks.push(disk);
                            nodeInfo.names.push(disk.name());
                            nodeInfo.changed = true;
                        }
                    });
                }
            });
            $.each(nodeDisks, function(nodeID, nodeInfo) {
                $.each(nodeInfo.disks, function(index, disk) {
                    if (!diskNames.contains(disk.name())) {
                        nodeInfo.disks.remove(disk);
                        nodeInfo.names.remove(disk.name());
                        nodeInfo.changed = true;
                    }
                });
                if (nodeInfo.changed === true) {
                    nodeInfo.disks.sort(function (a, b) {
                        return a.name() < b.name() ? -1 : 1;
                    });
                    nodeInfo.node.disks(nodeInfo.disks);
                }
                nodeInfo.node.disksLoading(self.initialRun);
            });
        };
        self.claimOSD = function(osds, disk, nodeID) {
            return $.Deferred(function(deferred) {
                app.showMessage(
                    $.t('alba:disks.claim.warning', { what: '<ul><li>' + disk + '</li></ul>', info: '' }).trim(),
                    $.t('ovs:generic.areyousure'),
                    [$.t('ovs:generic.yes'), $.t('ovs:generic.no')]
                )
                    .done(function(answer) {
                        if (answer === $.t('ovs:generic.yes')) {
                            generic.alertSuccess(
                                $.t('alba:disks.claim.started'),
                                $.t('alba:disks.claim.msgstarted')
                            );
                            api.post('alba/backends/' + self.albaBackend().guid() + '/add_units', {
                                data: { asds: osds }
                            })
                                .then(self.shared.tasks.wait)
                                .done(function() {
                                    generic.alertSuccess(
                                        $.t('alba:disks.claim.complete'),
                                        $.t('alba:disks.claim.success')
                                    );
                                    deferred.resolve();
                                })
                                .fail(function(error) {
                                    generic.alertError(
                                        $.t('ovs:generic.error'),
                                        $.t('alba:disks.claim.failed', { why: error })
                                    );
                                    deferred.reject();
                                });
                        } else {
                            deferred.reject();
                        }
                    });
            }).promise();
        };
        self.claimAll = function(osds, disks) {
            return $.Deferred(function(deferred) {
                app.showMessage(
                    $.t('alba:disks.claimall.warning', { which: '<ul><li>' + disks.join('</li><li>') + '</li></ul>', info: '' }).trim(),
                    $.t('ovs:generic.areyousure'),
                    [$.t('ovs:generic.yes'), $.t('ovs:generic.no')]
                )
                    .done(function(answer) {
                        if (answer === $.t('ovs:generic.yes')) {
                            generic.alertSuccess(
                                $.t('alba:disks.claimall.started'),
                                $.t('alba:disks.claimall.msgstarted')
                            );
                            api.post('alba/backends/' + self.albaBackend().guid() + '/add_units', {
                                data: { asds: osds }
                            })
                                .then(self.shared.tasks.wait)
                                .done(function() {
                                    generic.alertSuccess(
                                        $.t('alba:disks.claimall.complete'),
                                        $.t('alba:disks.claimall.success')
                                    );
                                    deferred.resolve();
                                })
                                .fail(function(error) {
                                    generic.alertError(
                                        $.t('ovs:generic.error'),
                                        $.t('alba:disks.claimall.failed', { why: error })
                                    );
                                    deferred.reject();
                                });
                        } else {
                            deferred.reject();
                        }
                    });
            }).promise();
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
                    .then(self.loadOSDs)
                    .then(self.fetchNodes)
                    .then(self.link)
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
