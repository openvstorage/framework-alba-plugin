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
    'jquery', 'durandal/app', 'knockout', 'plugins/dialog',
    'ovs/generic', 'ovs/shared',
    'viewmodels/containers/albanode/albanodebase', 'viewmodels/containers/albanode/albanode',
    'viewmodels/wizards/addosd/index', 'viewmodels/wizards/removeosd/index', 'viewmodels/wizards/registernodeundercluster/index',
    'viewmodels/services/subscriber', 'viewmodels/services/albanodecluster'
], function($, app, ko, dialog,
            generic, shared,
            AlbaNodeBase, AlbaNode,
            AddOSDWizard, RemoveOSDWizard, RegisterNodeWizard,
            subscriberService, albaNodeClusterService) {
    "use strict";
    var albaNodeClusterMapping = {
        // Avoid caching the same data twice in the mapping plugin. Stack is not required to be observable as we used the slot models instead
        // If stack had to be a viewmodel with observable properties: the slots would need to be created out of a copy of the stack as they now share the same instance
        // If the stack would not just be copied: the plugin would update either the stack or the slots first.
        // Since the slots is derived from the stack data (extracted data using Object.keys), the plugin will have cached the data object
        // (it pumps the full data object into the cache as a key and does a keylookup)
        // When it would update the next property, the plugin would detect that data object to apply was already applied and it won't update the object
        copy: ['stack'],
        'alba_nodes': {
            key: function(data) {  // For relation updates: check if the GUID has changed before discarding a model
                return ko.utils.unwrapObservable(data.guid)
            },
            create: function(options) {
                var data = options.data;
                var parent = options.parent;
                data.alba_node_cluster_guid = ko.utils.unwrapObservable(options.parent.guid);
                if (ko.utils.unwrapObservable(parent.stack) !== null) {
                    data.stack = generic.tryGet(ko.utils.unwrapObservable(parent.stack), data.node_id, {});
                    data.node_metadata = ko.utils.unwrapObservable(parent.cluster_metadata)
                }
                var node = new AlbaNode(data, parent.albaBackend);
                node.subscribeToSlotEvents();
                return node
                // @todo generate osds based on stack data to fill in
            }
        }
    };
    var albaBackendDetailContext = 'albaBackendDetail';
    /**
     * AlbaNodeClusterModel class
     * @param data: Data to bind into the model. This data maps with model in the Framework
     * @param albaBackend: Possible AlbaBackend viewmodel when this model has to operate in a backend-bound context
     * @constructor
     */
    function AlbaNodeClusterModel(data, albaBackend){
        var self = this;

        // Inherit from base
        AlbaNodeBase.call(self);

        // Variables
        self.shared      = shared;
        self.albaBackend = albaBackend;  // Attached albaBackendModel from the parent view

        // Observables
        self.expanded          = ko.observable(false);
        self.slotsLoading      = ko.observable(false);
        self.emptySlotMessage  = ko.observable();  // When the type would be generic
        self.emptySlots        = ko.observableArray([]);

        // Default data - replaces fillData - this always creates observables for the passed keys
        // Most of these properties are given by the API but setting them explicitly to have a view of how this model looks
        var vmData = $.extend({
            guid: null,
            name: null,
            ips: [],
            cluster_metadata: null,
            local_summary: null,
            stack: null,
            maintenance_services: [],
            supported_osd_types: [],
            read_only_mode: true,
            alba_nodes: [],
            alba_node_guids: [],
            slots: []
        }, data);

        ko.mapping.fromJS(vmData, albaNodeClusterMapping, self);  // Bind the data into this

        // Computed
        self.allSlots = ko.pureComputed(function() {  // Include the possible generated empty ones
            return [].concat(self.slots(), self.emptySlots())
        });
        self.canInitializeAll = ko.computed(function() {
            // @Todo implement
            return true;
        });
        self.canClaimAll = ko.computed(function() {
            // @Todo implement
            return true;
        });
        self.canDelete = ko.computed(function() {
            // @Todo implement
            return true;
        });
    }
    var functions = {
        // Functions
        // /**
        //  * Update the current view model with the supplied data
        //  * Overrules the default update to pull apart stack
        //  * @param data: Data to update on this view model (keys map with the observables)
        //  * @type data: Object
        //  */
        // update: function(data) {
        //     var self = this;
        //     if ('stack' in data) {
        //         data = $.extend(data, {'slots': self.generateSlotsByStack(data.stack)});
        //     }
        //     return AlbaNodeBase.prototype.update.call(this, data)
        // },
        /**
         * Refresh the current object instance by updating it with API data
         * @param options: Options to refresh with (Default to fetching the stack)
         * @returns {Deferred}
         */
        refresh: function(options){
            if (typeof options === 'undefined') {
                options = { contents: 'stack' }
            }
            var self = this;
            return albaNodeClusterService.loadAlbaNodeCluster(self.guid(), options)
                .done(function(data) {
                    self.update(data)
                })
                .fail(function(data) {
                    // @TODO remove
                    console.log('Failed to update current object: {0}'.format([data]))
                })
        },
        subscribeToNodeEvents: function() {
            var self = this;
            self.disposables.push(
                subscriberService.onEvents('albanodecluster_{0}:add_osds'.format([self.guid()]), albaBackendDetailContext).then(function(data) {
                    self.addOSDs(data);
                }),
                subscriberService.onEvents('albanodecluster_{0}:clear_slot'.format([self.guid()]), albaBackendDetailContext).then(function(data) {
                    self.removeSlot(data);
                }),
                subscriberService.onEvents('albanodecluster_{0}:claim_osds'.format([self.guid()]), albaBackendDetailContext).then(function(data) {
                    self.claimOSDs(data);
                }),
                subscriberService.onEvents('albanodecluster_{0}:restart_osd'.format([self.guid()]), albaBackendDetailContext).then(function(data) {
                    self.restartOSD(data);
                }),
                subscriberService.onEvents('albanodecluster_{0}:remove_osd'.format([self.guid()]), albaBackendDetailContext).then(function(data) {
                    self.removeOSD(data);
                }))
        },
        unsubscribeToNodeEvents: function() {
            var self = this;
            self.disposeDisposables()  // Only node events are registered under disposables for now
        },
        // @Todo implement
        deleteNode: function() {
        }
    };
    var wizards = {
        registerAlbaNode: function(){
            var self = this;
            dialog.show(new RegisterNodeWizard({
                modal: true,
                albaNodeCluster: self
            }));
        },
        /**
         * Fills in the slots for a AlbaNode in the cluster
         * The requested slots will be marked as 'active'
         * This functions is invoked through event handling (the AlbaNode will trigger the event)
         * @param nodeSlotData: Data about the node and it's slots
         * The given data contains a node (AlbaNode object as value) and slots (Array of Slot objects as value)
         */
        addOSDs: function(nodeSlotData) {  // Fill slots with active/passive side
            var self = this;
            if (!self.canInitializeAll() || self.read_only_mode() || !self.shared.user.roles().contains('manage')) {
                return;
            }
            var node = nodeSlotData.node;
            var slots = nodeSlotData.slots;
            if([node, slots].some(function(item) { return !item })) {
                throw new Error('No node or slots provided')
            }
            var wizard = new AddOSDWizard({
                    node: node,
                    nodeCluster: self,
                    slots: slots,
                    modal: true
            });
            // Set all slots to processing
            $.each(slots, function(index, slot) {
                slot.processing(true);
                $.each(slot.osds(), function(_, osd) {
                    osd.processing(true);
                });
            });

            wizard.closing.always(function() {
                $.each(slots, function(index, slot) {
                    slot.processing(false);
                    $.each(slot.osds(), function(_, osd) {
                        osd.processing(false);
                    });
                });
            });
            wizard.completed.always(function() {
                self.refresh()
                    .then(function(){
                        $.each(slots, function(index, slot) {
                            slot.processing(false);
                            $.each(slot.osds(), function(_, osd) {
                                osd.processing(false);
                            });
                        });
                    });
            });
            dialog.show(wizard);
        },
        claimOSDs: function(osdsToClaim) {
            throw new Error('To be implemented');
            var self = this;
            if (self.albaBackend === undefined) {
                return;
            }
            var slots = [];
            var osdData = [];
            var osds = [];
            var resetProcessingState = function() {
                $.each(osds, function(index, osd) {
                    osd.processing(false);
                });
                $.each(slots, function(index, slot) {
                    slot.processing(false);
                });
            };
            $.each(osdsToClaim, function(slotID, slotInfo) {
                var slot = self.findSlotBySlotID(slotID);
                slot.processing(true);
                slots.push(slot);
                $.each(slotInfo.osds, function(index, osd) {
                    osdData.push({
                        osd_type: osd.type(),
                        ips: osd.ips(),
                        port: osd.port(),
                        slot_id: slotID
                    });
                    osd.processing(true);
                    osds.push(osd);
                });
            });
            var osdIDs = osds.map(function(osd) {
                return osd.osd_id()
            });
            return app.showMessage(
                $.t('alba:osds.claim.warning', { what: '<ul><li>' + osdIDs.join('</li><li>') + '</li></ul>', multi: osdIDs.length === 1 ? '' : 's' }).trim(),
                $.t('alba:osds.claim.title', {multi: osdIDs.length === 1 ? '' : 's'}),
                [$.t('ovs:generic.yes'), $.t('ovs:generic.no')]
            )
                .then(function(answer) {
                    if (answer === $.t('ovs:generic.yes')) {
                        if (osdIDs.length === 1) {
                            generic.alertInfo(
                                $.t('alba:osds.claim.started'),
                                $.t('alba:osds.claim.started_msg_single', {what: osdIDs[0]})
                            );
                        } else {
                            generic.alertInfo(
                                $.t('alba:osds.claim.started'),
                                $.t('alba:osds.claim.started_msg_multi')
                            );
                        }
                        return albaBackendService.addOSDsOfNode(self.albaBackend.guid(), osdData, self.guid())
                            .then(function(data) {
                                if (data.length === 0) {
                                    if (osdIDs.length === 1) {
                                        generic.alertSuccess(
                                            $.t('alba:osds.claim.complete'),
                                            $.t('alba:osds.claim.success_single', {what: osdIDs[0]})
                                        );
                                    } else {
                                        generic.alertSuccess(
                                            $.t('alba:osds.claim.complete'),
                                            $.t('alba:osds.claim.success_multi')
                                        );
                                    }
                                } else {
                                    if (osdIDs.length === 1 || osdIDs.length === data.length) {
                                        generic.alertError(
                                            $.t('alba:osds.claim.failed_already_claimed'),
                                            $.t('alba:osds.claim.failed_already_claimed_all')
                                        );
                                    } else {
                                        generic.alertWarning(
                                            $.t('alba:osds.claim.warning_already_claimed'),
                                            $.t('alba:osds.claim.warning_already_claimed_some', {requested: osdIDs.length, actual: data.length})
                                        );
                                    }
                                }
                                self.refresh()
                                    .then(function() {
                                        resetProcessingState();
                                    });
                            }, function(error) {
                                error = generic.extractErrorMessage(error);
                                generic.alertError(
                                    $.t('ovs:generic.error'),
                                    $.t('alba:osds.claim.failed', { multi: osdIDs.length === 1 ? '' : 's', why: error })
                                );
                                resetProcessingState();
                            });
                    } else {
                        resetProcessingState();
                    }
                }, function(error) {
                    resetProcessingState();
                });
        },
        removeOSD: function(osd) {
            throw new Error('To be implemented');
            var self = this;
            var matchingSlot = self.findSlotByOSDID(osd.osd_id());
            if (matchingSlot === undefined) {
                return;
            }
            var wizard = new RemoveOSDWizard({
                    modal: true,
                    albaOSD: osd,
                    albaNode: self,
                    albaSlot: matchingSlot,
                    albaBackend: self.albaBackend
                });
            wizard.closing.always(function() {
                // Indicates that it was canceled
                osd.processing(false);
                matchingSlot.processing(false);
            });
            wizard.completed.always(function() {
                self.refresh()
                    .then(function() {
                        osd.processing(false);
                        matchingSlot.processing(false);
                    });
            });
            osd.processing(true);
            matchingSlot.processing(true);
            dialog.show(wizard);
        },
        restartOSD: function(osd) {
            throw new Error('To be implemented');
            var self = this;
            osd.processing(true);
            generic.alertInfo(
                $.t('alba:osds.restart.started'),
                $.t('alba:osds.restart.started_msg', { what: osd.osdID() })
            );
            return albaNodeService.restartOSD(self.guid(), osd.osdID())
                .then(function() {
                    generic.alertSuccess(
                        $.t('alba:osds.restart.complete'),
                        $.t('alba:osds.restart.success', {what: osd.osdID()})
                    );
                }, function(error) {
                    error = generic.extractErrorMessage(error);
                    generic.alertError(
                        $.t('ovs:generic.error'),
                        $.t('alba:osds.restart.failed', {what: osd.osdID(), why: error})
                    );
                })
                .always(function() {
                    osd.processing(false);
                });
        },
        removeSlot: function(slot) {
            throw new Error('To be implemented');
            var self = this;
            slot.processing(true);
            $.each(slot.osds(), function(_, osd) {
                osd.processing(true);
            });
            generic.alertInfo(
                $.t('alba:slots.remove.started'),
                $.t('alba:slots.remove.started_msg', { what: slot.slot_id() }));
            (function(currentSlot) {
                return albaNodeService.removeSlot(self.guid(), currentSlot.slot_id())
                    .then(function() {
                        generic.alertSuccess(
                            $.t('alba:slots.remove.complete'),
                            $.t('alba:slots.remove.success', {what: currentSlot.slot_id()})
                        );
                    }, function(error) {
                        error = generic.extractErrorMessage(error);
                        generic.alertError(
                            $.t('ovs:generic.error'),
                            $.t('alba:slots.remove.failed', {what: currentSlot.slot_id(), why: error})
                        );
                    })
                    .always(function() {
                        self.refresh()
                            .then(function() {
                                currentSlot.processing(false);
                                $.each(currentSlot.osds(), function(_, osd) {
                                    osd.processing(false);
                                });
                            });
                    })
            })(slot);
        }
    };
    // Prototypical inheritance
    AlbaNodeClusterModel.prototype = $.extend(AlbaNodeBase.prototype, functions, wizards);
    return AlbaNodeClusterModel
});
