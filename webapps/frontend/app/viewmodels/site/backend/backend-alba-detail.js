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
    'jquery', 'durandal/app', 'knockout', 'plugins/router', 'plugins/dialog', 'd3',
    'ovs/shared', 'ovs/generic', 'ovs/refresher', 'ovs/api',
    'viewmodels/containers/shared/base_container', 'viewmodels/containers/backend/albabackend', 'viewmodels/containers/albanode/albanode',
    'viewmodels/containers/backend/backend', 'viewmodels/containers/backend/backendtype', 'viewmodels/containers/domain/domain',
    'viewmodels/containers/storagerouter/storagerouter', 'viewmodels/containers/albanode/albaosd',
    'viewmodels/containers/albanode/albanodecluster',
    'viewmodels/wizards/addnode/index', 'viewmodels/wizards/addpreset/index', 'viewmodels/wizards/linkbackend/index',
    'viewmodels/wizards/unlinkbackend/index', 'viewmodels/wizards/editmaintenance/index',
    'viewmodels/services/albanode', 'viewmodels/services/albanodecluster', 'viewmodels/services/subscriber'
], function($, app, ko, router, dialog, d3,
            shared, generic, Refresher, api,
            BaseContainer, AlbaBackend, AlbaNode, Backend, BackendType, Domain, StorageRouter, AlbaOSD, NodeCluster,
            AddNodeWizard, AddPresetWizard, LinkBackendWizard, UnlinkBackendWizard, EditMaintenanceWizard,
            albaNodeService, albaNodeClusterService, subscriberService) {
    "use strict";
    var viewModelMapping = {
        backend: {
            key: function(data) {  // For relation updates: check if the GUID has changed before discarding a model
                return ko.utils.unwrapObservable(data.guid)
            },
            create: function(options) {
                return new Backend(null);
            }
        },
        alba_backend: {
            key: function(data) {  // For relation updates: check if the GUID has changed before discarding a model
                return ko.utils.unwrapObservable(data.guid)
            },
            create: function(options) {
                return new AlbaBackend(null);
            }
        },
        alba_node_clusters: {
            key: function(data) {  // For relation updates: check if the GUID has changed before discarding a model
                return ko.utils.unwrapObservable(data.guid)
            },
            create: function(options) {
                if (options.parent.alba_backend === undefined) {
                    return null
                }
                return new NodeCluster(options.data, options.parent.alba_backend);
            },
            update: function (options){
                options.target.update(options.data);
                return options.target
            }
        },
        alba_nodes_discovered: {
            key: function(data) {  // For relation updates: check if the GUID has changed before discarding a model
                return ko.utils.unwrapObservable(data.guid)
            },
            create: function(options) {
                if (options.parent.alba_backend === undefined) {
                    return null
                }
                // This object has not yet been converted to work with ko.mapping thus manually overriden the create
                return new AlbaNode(null, options.parent.alba_backend);
            },
            update: function (options){
                options.target.update(options.data);
                return options.target
            }
        },
        alba_nodes_registered: {
            key: function(data) {  // For relation updates: check if the GUID has changed before discarding a model
                return ko.utils.unwrapObservable(data.guid)
            },
            create: function(options) {
                if (options.parent.alba_backend === undefined) {
                    return null
                }
                // This object has not yet been converted to work with ko.mapping thus manually overriden the create
                var storageNode = new AlbaNode(options.data, options.parent.alba_backend, options.parent);
                storageNode.subscribeToSlotEvents();
                return storageNode
            },
            update: function (options){
                options.target.update(options.data);
                return options.target
            },
            arrayChanged: function(event, item) {
                // Undocumented callback in the plugin. This function notifies what 'event' of what 'item' happened in the array
                // The possible events are:
                // - 'retained': item is kept, callback hooking can be done through the 'update' callback
                // - 'added': item is created, callback hooking can be done through the through the 'create' callback
                // - 'deleted': 'item' was removed from the array
                // Hooking in the delete to unsubscribe from our events
                if (event === 'deleted' && item && item.unsubscribeToSlotEvents && typeof item.unsubscribeToSlotEvents === 'function') {
                    item.unsubscribeToSlotEvents()
                }
            }
        }
    };
    var viewModelContext = 'albaBackendDetail';

    function AlbaBackendDetail() {
        var self = this;
        BaseContainer.call(self);
        // Constants
        var colorRange = d3.scale.ordinal().range(['#e6e6e6', '#b2b2b2', '#808080','#377eb8', '#4daf4a', '#984ea3',
            '#ff7f00', '#ffff33', '#a65628', '#f781bf', '#999999']);
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
        self.discoveredNodes        = ko.observableArray([]);
        self.loadingNodes           = ko.observable(true);
        self.domains                = ko.observableArray([]);
        self.initialRun             = ko.observable(true);
        self.otherAlbaBackendsCache = ko.observable({});
        self.remoteStack            = ko.observableArray([]);

        // Subscriptions
        self.disposables.push(subscriberService.onEvents('alba_backend:load', viewModelContext).then(function(data){
            var albaBackendGuid, responseEvent;
            if (typeof data === 'object') {
                albaBackendGuid = data.albaBackendGuid;
                responseEvent = data.response;
            } else {
                albaBackendGuid = data;
            }
            var cache = self.otherAlbaBackendsCache(), ab;
            return $.when()
                .then(function() {
                    if (!cache.hasOwnProperty(albaBackendGuid)) {
                        ab = new AlbaBackend(albaBackendGuid);
                        return ab.load('backend')
                            .then(function () {
                                ab.backend.load();  // Don't care about this item so not waiting until it is loaded
                                cache[albaBackendGuid] = ab;
                                self.otherAlbaBackendsCache(cache);
                                return ab.toJS()
                            });
                    }
                    return cache[albaBackendGuid].toJS();
                })
                .then(function(data){
                    if (responseEvent) {
                        subscriberService.trigger(responseEvent, data)
                    }
                });
        }));
        var vmData = {
            backend: {},
            alba_backend: {},
            alba_node_clusters: [],
            alba_nodes_discovered: [],
            alba_nodes_registered: []
        };

        ko.mapping.fromJS(vmData, viewModelMapping, self);  // Bind the data into this

        // Computed
        self.nodesAndCluster = ko.pureComputed(function() {
            return [].concat(self.alba_node_clusters(), self.alba_nodes_registered());
        });
        self.domainGuids = ko.pureComputed(function() {
            if (!self.backend.guid()) { return []; }
            return self.domains().map(function(domain){ return domain.guid() })
        });
        self.expanded = ko.computed({
            write: function(value) {
                $.each(self.nodesAndCluster(), function(index, item) {
                    item.expanded(value);
                });
            },
            read: function() {
                return self.nodesAndCluster().every(function(node){
                    return node.expanded()
                });
            }
        });
        self.anyCollapsed = ko.pureComputed(function() {
            /**
             * Check if any node is collapsed
             * Different than the expanded check in the way this will return true when any are collapsed as opposed to all
             */
            return self.nodesAndCluster().some(function(node){
                    return !node.expanded()
            });
        });
        self.showDetails = ko.pureComputed(function() {
            return self.alba_backend.initialized() && self.backend.guid();
        });
        self.showActions = ko.pureComputed(function() {
            return self.showDetails() && !['installing', 'new'].contains(self.backend.status()) && self.alba_backend.scaling() !== undefined;
        });

        // Subscriptions
        self.otherAlbaBackends = ko.computed(function() {  // Give color to all cached backends
            var albaBackends = [], cache = self.otherAlbaBackendsCache();
            $.each(cache, function(index, albaBackend) {
                if (albaBackend.guid() !== self.alba_backend.guid()) {
                    albaBackend.color(colorRange(albaBackend.guid()));
                    albaBackends.push(albaBackend);
                }
            });
            return albaBackends;
        });
    }

    var functions = {
        refresh: function() {
            var self = this;
            self.updateNodes(true);
        },
        load: function() {
            var self = this;
            var backend = self.backend, backendType;
            return backend.load('live_status')
                .then(function(backendData) {
                    if (backend.backendType() === undefined) {
                        backendType = new BackendType(backend.backendTypeGuid());
                        backendType.load();
                        backend.backendType(backendType);
                    }
                    if (backendData.hasOwnProperty('alba_backend_guid') && backendData.alba_backend_guid !== null) {
                        if (!self.alba_backend.initialized()) {
                            self.alba_backend.guid(backendData.alba_backend_guid);
                        }
                        return self.alba_backend.load()
                            .then(self.alba_backend.getAvailableActions());
                    }
                })
        },
        formatBytes: function(value) {
            return generic.formatBytes(value);
        },
        formatPercentage: function(value) {
            if (isNaN(value)) {
                return "0 %";
            } else {
                return generic.formatPercentage(value);
            }
        },
        /**
         * Updates all relevant data for this page
         * @return {Promise}
         */
        updateData: function() {
            var self = this;
            if (!self.alba_backend.initialized() || self.alba_backend.scaling() === 'GLOBAL') {
                return $.when()
            }
            // Re-use alba nodes model and afterwards we can update those models themselves. The same reference is then passed to every item
            return $.when(self.updateNodeClusters(), self.updateNodes(), self.updateNodes(true))
                .then(function(nodeClustersData, nodesData, discoveredNodesData){
                    // Serialize the cluster and attach the alba node data to it
                    return {
                        alba_nodes_registered: nodesData,
                        alba_node_clusters: nodeClustersData,
                        alba_nodes_discovered: discoveredNodesData
                    }
                })
                .always(function() {
                    self.loadingNodes(false)
                })

        },
        updateNodeClusters: function() {
            var self = this;
            if (!self.alba_backend.initialized() || self.alba_backend.scaling() === 'GLOBAL') {
                return $.when()
            }
            return $.when()
                .then(function() {
                    if (!generic.xhrCompleted(self.nodeClustersHandle)) {
                        return
                    }
                    var options = {contents: 'stack,cluster_metadata,local_summary,read_only_mode,_relations,_relation_contents_alba_nodes=local_summary'};
                    return self.nodeClustersHandle = albaNodeClusterService.loadAlbaNodeClusters(options)
                        .then(function(data) {
                            var updateData = {alba_node_clusters: data.data};
                            self.update(updateData);
                            return data.data
                        })
                })
        },
        updateNodes: function(discover) {
            var self = this;
            discover = !!discover;
            var key = discover? 'alba_nodes_discovered': 'alba_nodes_registered';
            if (!self.alba_backend.initialized() || self.alba_backend.scaling() === 'GLOBAL') {
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
                        // Reason to making it conditional: discovered nodes are generated in the API and the decorator uses
                        // the results of the previous DataList. These items don't exist in reality for the discovered nodes so nothing
                        // is returned
                        query: discover? null : JSON.stringify({  // Only fetch non-clustered nodes
                            type: 'AND',
                            items: [['alba_node_cluster_guid', 'EQUALS', null]]
                        })
                    };
                    return self.nodesHandle[discover] = albaNodeService.loadAlbaNodes(options, undefined, true)
                        .then(function (data) {
                            // var updateData = {[key]: data.data};  in ES6 <<
                            var updateData = {};
                            updateData[key] = data.data;
                            self.update(updateData);
                            return data.data;  // Unwrap
                        })
                })
        },
        loadBackendOSDs: function() {
            var self = this;
            var data = self.alba_backend.toJS();
            if (data === undefined || !data.hasOwnProperty('remote_stack')) {
                return;
            }
            var remoteStacks = [];
            $.each(data.remote_stack, function(alba_backend_guid, stack_data) {
                stack_data.alba_backend_guid = alba_backend_guid;
                remoteStacks.push(stack_data);
            });
            self.remoteStack(remoteStacks);
            self.remoteStack.sort(function(stack1, stack2) {
                return stack1.name < stack2.name ? -1 : 1;
            });
        },
        loadDomains: function() {
            var self = this;
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
        }
    };

    var wizards = {
        linkBackend: function() {
            var self = this;
            if (!self.alba_backend.initialized() || self.alba_backend.scaling() !== 'GLOBAL') {
                return
            }
            dialog.show(new LinkBackendWizard ({
                modal: true,
                target: self.alba_backend
            }));
        },
        editPreset: function(data) {
            var self = this;
            dialog.show(new AddPresetWizard({
                modal: true,
                currentPreset: data,
                backend: self.alba_backend,
                currentPresets: self.alba_backend.enhancedPresets(),
                editPreset: true
            }));
        },
        unlinkBackend: function(info) {
            var self = this;
            dialog.show(new UnlinkBackendWizard ({
                modal: true,
                target: self.alba_backend,
                linkedOSDInfo: info
            }));
        },
        register: function(node) {
            var self = this;
            var oldNode = undefined;
            $.each(self.alba_nodes_registered(), function(index, registeredNode) {
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
        },
        addPreset: function() {
            var self = this;
            dialog.show(new AddPresetWizard({
                modal: true,
                backend: self.alba_backend,
                currentPresets: self.alba_backend.enhancedPresets(),
                editPreset: false
            }));
        },
        addNode: function() {
            var node = new AlbaNode();
            dialog.show(new AddNodeWizard({
                modal: true,
                newNode: node,
                oldNode: undefined,
                confirmOnly: false
            }));
        },
        removeBackend: function() {
            var self = this;
            return $.Deferred(function(deferred) {
                if (!self.alba_backend.initialized() || !self.alba_backend.availableActions().contains('REMOVE')) {
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
                                $.t('alba:detail.delete.started_msg', {what: self.alba_backend.name()})
                            );
                            router.navigateBack();
                            api.del('alba/backends/' + self.alba_backend.guid())
                                .then(self.shared.tasks.wait)
                                .done(function() {
                                    generic.alertSuccess(
                                        $.t('alba:detail.delete.success'),
                                        $.t('alba:detail.delete.success_msg', {what: self.alba_backend.name()})
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
        },
        removePreset: function(name) {
            var self = this;
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
                            api.post('alba/backends/' + self.alba_backend.guid() + '/delete_preset', { data: { name: name } })
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
        },
        editMaintenance: function() {
            var self = this;
            dialog.show(new EditMaintenanceWizard({
                modal: true,
                backend: self.alba_backend
            }));
        }
    };

    var durandalFunctions = {
        activate: function(mode, guid) {
            var self = this;
            self.backend.guid(guid);
            self.refresher.init(function() {
                self.loadDomains();
                return self.load()
                    .then(self.updateData.bind(self))
                    .then(self.loadBackendOSDs.bind(self))
                    .then(function() {
                        if (self.initialRun() === true) {
                            self.initialRun(false);
                            self.refresher.skipPause = true;
                        }
                    })
            }, 5000);
            self.refresher.run();
            self.refresher.start();
        },
        deactivate: function() {
            var self = this;
            $.each(self.widgets, function(index, item) {
                item.deactivate();
            });
            self.refresher.stop();
            // Remove all event listeners of the underlying nodes
            $.each([].concat(self.alba_nodes_discovered(), self.alba_nodes_registered()), function(index, node) {
                node.unsubscribeToSlotEvents()
            });
            // Remove our own disposables
            self.disposeAll();
            // Remove all associated events related to this viewModelcontext
            subscriberService.dispose(viewModelContext);
        }
    };

    AlbaBackendDetail.prototype = $.extend({}, BaseContainer.prototype, functions, wizards, durandalFunctions);
    return AlbaBackendDetail
});
