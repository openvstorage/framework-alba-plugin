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
    'viewmodels/containers/shared/base_container', 'viewmodels/containers/backend/albabackend', 'viewmodels/containers/albanode/albanode',
    'viewmodels/containers/backend/backend', 'viewmodels/containers/backend/backendtype', 'viewmodels/containers/domain/domain',
    'viewmodels/containers/storagerouter/storagerouter', 'viewmodels/containers/albanode/albaosd',
    'viewmodels/containers/albanode/albanodecluster',
    'viewmodels/wizards/addnode/index', 'viewmodels/wizards/addpreset/index', 'viewmodels/wizards/linkbackend/index',
    'viewmodels/wizards/unlinkbackend/index',
    'viewmodels/services/albanodeservice', 'viewmodels/services/albanodeclusterservice'
], function($, app, ko, router, dialog,
            shared, generic, Refresher, api,
            BaseContainer, AlbaBackend, AlbaNode, Backend, BackendType, Domain, StorageRouter, AlbaOSD, NodeCluster,
            AddNodeWizard, AddPresetWizard, LinkBackendWizard, UnlinkBackendWizard,
            albaNodeService, albaNodeClusterService) {
    "use strict";
    var viewModelMapping = {
        'alba_node_clusters': {
            key: function(data) {  // For relation updates: check if the GUID has changed before discarding a model
                return ko.utils.unwrapObservable(data.guid)
            },
            create: function(options) {
                if (options.parent.albaBackend() === undefined) {
                    return null
                }
                return new NodeCluster(options.data.guid);
            }
        },
        'alba_nodes_discovered': {
            key: function(data) {  // For relation updates: check if the GUID has changed before discarding a model
                return ko.utils.unwrapObservable(data.guid)
            },
            create: function(options) {
                if (options.parent.albaBackend() === undefined) {
                    return null
                }
                // This object has not yet been converted to work with ko.mapping thus manually overriden the create
                var storage_node = new AlbaNode(options.data.nodeID);
                storage_node.fillData(options.data);
                return storage_node
            }
        },
        'alba_nodes_registered': {
            key: function(data) {  // For relation updates: check if the GUID has changed before discarding a model
                return ko.utils.unwrapObservable(data.guid)
            },
            create: function(options) {
                if (options.parent.albaBackend() === undefined) {
                    return null
                }
                // This object has not yet been converted to work with ko.mapping thus manually overriden the create
                var storage_node = new AlbaNode(options.data.node_id, options.parent.albaBackend(), options.parent);
                storage_node.fillData(options.data);
                return storage_node
            }
        }
    };
    function viewModel() {
        var self = this;
        BaseContainer.call(self);
        // Variables
        self.domainCache        = {};
        self.shared             = shared;
        self.generic            = generic;
        self.guard              = { authenticated: true };
        self.refresher          = new Refresher();
        self.widgets            = [];
        self.nodesHandle        = {};
        self.nodeClustersHandle = undefined;
        self.storageRouterCache = {};
        self.loadDomainsHandle  = undefined;

        // Observables
        self.albaBackend            = ko.observable();
        self.backend                = ko.observable();
        self.discoveredNodes        = ko.observableArray([]);
        self.dNodesLoading          = ko.observable(false);
        self.domains                = ko.observableArray([]);
        self.initialRun             = ko.observable(true);
        self.localSummary           = ko.observable();
        self.otherAlbaBackendsCache = ko.observable({});
        self.registeredNodes        = ko.observableArray([]);
        self.registeredNodesNodeIDs = ko.observableArray([]);
        self.remoteStack            = ko.observableArray([]);
        self.rNodesLoading          = ko.observable(true);

        var vmData = {
            'alba_nodes_discovered': [],
            'alba_nodes_registered': []
        };

        ko.mapping.fromJS(vmData, viewModelMapping, self);  // Bind the data into this

        // Computed
        self.domainGuids = ko.pureComputed(function() {
            if (self.backend() === undefined) { return []; }
            return self.domains().map(function(domain){ return domain.guid() })
        });
        self.filteredDiscoveredNodes = ko.pureComputed(function() {
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
        self.anyCollapsed = ko.pureComputed(function() {
            /**
             * Check if any node is collapsed
             * Different than the expanded check in the way this will return true when any are collapsed as opposed to all
              */
            var collapsed = false;
            $.each(self.registeredNodes(), function(index, node) {
                if (node.expanded() === false) {
                    collapsed = true;
                    return false;
                }
            });
            return collapsed;
        });
        self.otherAlbaBackends = ko.pureComputed(function() {
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
        self.showDetails = ko.pureComputed(function() {
            return self.albaBackend() !== undefined && self.backend() !== undefined;
        });
        self.showActions = ko.pureComputed(function() {
            return self.showDetails() && !['installing', 'new'].contains(self.backend().status()) && self.albaBackend().scaling() !== undefined;
        });

        // Functions
        self.refresh = function() {
            self.dNodesLoading(true);
            self.fetchNodes(true);
        };
        self.load = function() {
            return $.Deferred(function (deferred) {
                var backend = self.backend(), backendType;
                backend.load('live_status')
                    .then(function(backendData) {
                        if (backend.backendType() === undefined) {
                            backendType = new BackendType(backend.backendTypeGuid());
                            backendType.load();
                            backend.backendType(backendType);
                        }
                        if (backendData.hasOwnProperty('alba_backend_guid') && backendData.alba_backend_guid !== null) {
                            if (self.albaBackend() === undefined) {
                                self.albaBackend(new AlbaBackend(backendData.alba_backend_guid));
                            }
                            return self.albaBackend().load()
                                .then(self.albaBackend().getAvailableActions);
                        }
                        deferred.reject();
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

        /**
         * Fetches all relevant data for this page
         * @param discover: Discover new nodes
         * @return {Deferred}
         */
        self.loadData = function(discover) {
            discover = !!discover;
            if (self.albaBackend() === undefined || self.albaBackend().scaling() === 'GLOBAL') {
                return $.when()
            }
            // Re-use alba nodes model and afterwards we can update those models themselves. The same reference is then passed to every item
            $.when(self.fetchNodeClusters(), self.fetchNodes(discover))
                .then(function(nodeClustersData, nodesData){
                    // Serialize the cluster and attach the alba node data to it
                    self.update({
                        alba_nodes_registered: nodesData,
                        alba_node_clusters: nodeClustersData
                    })
                })

        };
        self.fetchNodeClusters = function() {
            if (self.albaBackend() === undefined || self.albaBackend().scaling() === 'GLOBAL') {
                return $.when()
            }
            return $.when()
                .then(function() {
                    if (!generic.xhrCompleted(self.nodeClustersHandle)) {
                        return
                    }
                    var options = {contents: '_relations,_relation_contents_alba_nodes=""'};
                    return self.nodeClustersHandle = albaNodeClusterService.loadAlbaNodeClusters(options)
                        .then(function(data) {
                            return data.data
                        })
                })
        };
        self.fetchNodes = function(discover) {
            discover = !!discover;
            if (self.albaBackend() === undefined || self.albaBackend().scaling() === 'GLOBAL') {
                return;
            }
            return $.when()
                .then(function() {
                    if (!generic.xhrCompleted(self.nodesHandle[discover])) {
                        return
                    }
                    // Always fetch storagerouter relation and serialize them too
                    var contents = '_relations,_relation_contents_storagerouter=""';
                    if (discover === true) {
                        contents += ',ips,stack,node_metadata,local_summary';
                    } else {
                        contents += ',stack,node_metadata,local_summary,read_only_mode';
                    }
                    var options = {
                        sort: 'storagerouter.name,storagerouter.ip,ip',
                        contents: contents,
                        discover: discover,
                        query: JSON.stringify({  // Only fetch non-clustered nodes
                            type: 'AND',
                            items: [['alba_node_cluster', 'EQUALS', null]]
                        })
                    };
                    return self.nodesHandle[discover] = albaNodeService.loadAlbaNodes(options)
                        .then(function (data) {
                            var apiData = data.data;
                            apiData.sort(function(a, b){
                                if (a.storagerouter !== null && b.storagerouter !== null) {
                                    return a.storagerouter.name < b.storagerouter.name ? -1 : 1;
                                } else if (a.storagerouter === null && b.storagerouter === null) {
                                    if (![undefined, null].contains(a.ip) && ![undefined, null].contains(b.ip)){
                                        return generic.ipSort(a.ip, b.ip);
                                    } else {
                                        return a.node_id < b.node_id ? -1 : 1;
                                    }
                                }
                                return a.storagerouter !== null ? -1 : 1;
                            });
                            return apiData;
                        })
                })
        };
        self.loadBackendOSDs = function() {
            var data = self.albaBackend().rawData;
            if (data === undefined || !data.hasOwnProperty('remote_stack') || !data.hasOwnProperty('local_summary')) {
                return;
            }
            self.localSummary(data.local_summary);
            var remoteStacks = [];
            $.each(data.remote_stack, function(alba_backend_guid, stack_data) {
                stack_data.alba_backend_guid = alba_backend_guid;
                remoteStacks.push(stack_data);
            });
            self.remoteStack(remoteStacks);
            self.remoteStack.sort(function(stack1, stack2) {
                return stack1.name < stack2.name ? -1 : 1;
            });
        };
        self.loadDomains = function() {
            return $.Deferred(function(deferred) {
                if (generic.xhrCompleted(self.loadDomainsHandle)) {
                    self.loadDomainsHandle = api.get('domains', {
                        queryparams: { sort: 'name', contents: '' }
                    })
                        .done(function(data) {
                            var guids = [], ddata = {};
                            $.each(data.data, function(index, item) {
                                guids.push(item.guid);
                                ddata[item.guid] = item;
                            });
                            generic.crossFiller(
                                guids, self.domains,
                                function(guid) {
                                    return new Domain(guid);
                                }, 'guid'
                            );
                            $.each(self.domains(), function(index, domain) {
                                if (ddata.hasOwnProperty(domain.guid())) {
                                    domain.fillData(ddata[domain.guid()]);
                                }
                                self.domainCache[domain.guid()] = domain;
                            });
                            self.domains.sort(function(dom1, dom2) {
                                return dom1.name() < dom2.name() ? -1 : 1;
                            });
                            deferred.resolve();
                        })
                        .fail(deferred.reject);
                } else {
                    deferred.reject();
                }
            }).promise();
        };
        self.getNodeById = function(nodeID){
            var node_to_return = undefined;
            $.each(self.registeredNodes(), function(index, node) {
              if (node.nodeID() === nodeID) {
                  node_to_return = node;
                  return false
              }
            });
            return node_to_return
        };

        // Wizards
        self.linkBackend = function() {
            if (self.albaBackend().linkedBackendGuids() === undefined || self.albaBackend().linkedBackendGuids() === null) {
                return;
            }
            dialog.show(new LinkBackendWizard ({
                modal: true,
                target: self.albaBackend()
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
        self.unlinkBackend = function(info) {
            dialog.show(new UnlinkBackendWizard ({
                modal: true,
                target: self.albaBackend(),
                linkedOSDInfo: info
            }));
        };
        self.register = function(node) {
            var oldNode = undefined;
            $.each(self.registeredNodes(), function(index, registeredNode) {
                if (registeredNode.ip() === node.ip()) {
                    oldNode = registeredNode;
                    return false;
                }
            });
            dialog.show(new AddNodeWizard({
                modal: true,
                newNode: node,
                oldNode: oldNode,
                confirmOnly: true
            }));
        };
        self.addPreset = function() {
            dialog.show(new AddPresetWizard({
                modal: true,
                backend: self.albaBackend(),
                currentPresets: self.albaBackend().enhancedPresets(),
                editPreset: false
            }));
        };
        self.addNode = function() {
            var node = new AlbaNode();
            dialog.show(new AddNodeWizard({
                modal: true,
                newNode: node,
                oldNode: undefined,
                confirmOnly: false
            }));
        };
        self.removeBackend = function() {
            return $.Deferred(function(deferred) {
                if (self.albaBackend() === undefined || !self.albaBackend().availableActions().contains('REMOVE')) {
                    deferred.reject();
                    return;
                }
                app.showMessage(
                    $.t('alba:detail.delete.warning'),
                    $.t('ovs:generic.are_you_sure'),
                    [$.t('ovs:generic.yes'), $.t('ovs:generic.no')]
                )
                    .done(function(answer) {
                        if (answer === $.t('ovs:generic.yes')) {
                            generic.alertInfo(
                                $.t('alba:detail.delete.started'),
                                $.t('alba:detail.delete.started_msg', {what: self.albaBackend().name()})
                            );
                            router.navigateBack();
                            api.del('alba/backends/' + self.albaBackend().guid())
                                .then(self.shared.tasks.wait)
                                .done(function() {
                                    generic.alertSuccess(
                                        $.t('alba:detail.delete.success'),
                                        $.t('alba:detail.delete.success_msg', {what: self.albaBackend().name()})
                                    );
                                    deferred.resolve();
                                })
                                .fail(function(error) {
                                    error = generic.extractErrorMessage(error);
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
                    $.t('ovs:generic.are_you_sure'),
                    [$.t('ovs:generic.yes'), $.t('ovs:generic.no')]
                )
                    .done(function(answer) {
                        if (answer === $.t('ovs:generic.yes')) {
                            generic.alertInfo(
                                $.t('alba:presets.delete.started'),
                                $.t('alba:presets.delete.started_msg')
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
                                    error = generic.extractErrorMessage(error);
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

        // Durandal
        self.activate = function(mode, guid) {
            self.backend(new Backend(guid));
            self.refresher.init(function() {
                self.loadDomains();
                return self.load()
                    .then(self.fetchNodes)  // Fetch all known nodes
                    .then(function() { self.fetchNodes(true); })  // Discover new ones
                    .then(self.loadBackendOSDs)
                    .then(function() {
                        if (self.initialRun() === true) {
                            self.initialRun(false);
                            self.refresher.skipPause = true;
                        }
                    })
                    .then(self.loadData)
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
    }
    return viewModel
});
