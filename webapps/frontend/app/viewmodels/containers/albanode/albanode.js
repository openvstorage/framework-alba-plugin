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
    'ovs/generic', 'ovs/api', 'ovs/shared',
    'viewmodels/containers/albanode/albanodebase', 'viewmodels/containers/albanode/albaslot', 'viewmodels/containers/albanode/localsummary',
    'viewmodels/containers/storagerouter/storagerouter',
    'viewmodels/wizards/addosd/index', 'viewmodels/wizards/removeosd/index',
    'viewmodels/services/subscriber'
], function($, app, ko, dialog,
            generic, api, shared,
            AlbaNodeBase, Slot, LocalSummary, StorageRouter,
            AddOSDWizard, RemoveOSDWizard,
            subscriberService) {
    "use strict";
    var viewModelMapping = {
        storagerouter: {
            key: function(data) {  // For relation updates: check if the GUID has changed before discarding a model
                return ko.utils.unwrapObservable(data.guid)
            },
            create: function(options) {  // This object has not yet been converted to work with ko.mapping thus manually overriden the create
                var storagerouter;
                if (options.data === null){
                    storagerouter = new StorageRouter(null);
                    storagerouter.loaded(true);
                    return storagerouter
                }
                storagerouter = new StorageRouter(ko.utils.unwrapObservable(options.data.guid));
                storagerouter.fillData((ko.utils.unwrapObservable(options.data)));
                storagerouter.loaded(true);
                return storagerouter
            }
        },
        local_summary: {
            create: function(options) {
                var data = generic.tryGet(options.data, 'devices', {});
                return new LocalSummary(data)
            }
        },
        slots: {
            key: function(data) {  // For relation updates: check if the GUID has changed before discarding a model
                return ko.utils.unwrapObservable(data.slot_id)
            },
            create: function(options) {
                // Attach metadata of this model. Metadata is dependant on the node type and won't change so no need to make it a model
                var data = $.extend({}, options.data);
                data.node_metadata = options.parent.node_metadata;
                return new Slot(data);
            }
        }
    };

    /**
     * AlbaNode class
     * @param albaBackend: Linked Albackend mode
     * @param parentVM: ParentVM that should be linked
     * @param data: Data that represents this AlbaNode
     * Note: the osds have to be explicitely set to allow the knockout mapping plugin to update them.
     * They can be generated out of the stack property but must be fed in into the data explicitly
     */
    function AlbaNode(data, albaBackend, parentVM) {
        var self = this;

        AlbaNodeBase.call(this);  // Inherit from Base

        // Variables
        self.shared      = shared;
        self.albaBackend = albaBackend;
        self.parentVM    = parentVM;  // Parent ViewModel, so backend-alba-detail page in this case

        // Handles
        self.loadLogFilesHandle = undefined;

        // Observables
        self.downLoadingLogs   = ko.observable(false);
        self.downloadLogState  = ko.observable($.t('alba:support.download_logs'));
        self.emptySlotMessage  = ko.observable();
        self.expanded          = ko.observable(false);
        self.loaded            = ko.observable(false);
        self._localSummary     = ko.observable();
        self.slotsLoading      = ko.observable(true);

        var vmData = $.extend({
            alba_node_cluster: undefined,  // Setting these to undefined as we need to check if a relation was defined
            alba_node_cluster_guid: undefined,
            ip: null,
            ips: [],
            guid: null,
            local_summary: {},
            name: null,
            node_id: null,
            node_metadata: {},
            osd_guids: [],
            slots: [],
            package_information: {},
            port: null,
            stack: null,
            storagerouter: null,  // Substituted for a viewmodel by the mapping
            storagerouter_guid: null,
            username: null,
            read_only_mode: false,
            type: null
        }, data || {});

        vmData = $.extend(vmData, {'slots': self.generateSlotsByStack(vmData.stack || {})});  // Add slot info
        ko.mapping.fromJS(vmData, viewModelMapping, self);  // Bind the data into this
        self.loaded(true);

        // Computed
        self.isPartOfCluster = ko.pureComputed(function() {
           if (self.alba_node_cluster_guid === undefined) {
               throw new Error('Unable to determine if this node is part of a cluster because the information has not been retrieved')
           }
           return self.alba_node_cluster_guid !== null
        });
        self.canInitializeAll = ko.pureComputed(function() {
            var hasUninitialized = false;
            $.each(self.slots(), function(index, slot) {
                if (slot.osds().length === 0 && slot.processing() === false) {
                    hasUninitialized = true;
                    return false;
                }
            });
            return hasUninitialized;
        });
        self.canClaimAll = ko.pureComputed(function() {
            if (self.albaBackend === undefined) {
                return false;
            }
            var hasUnclaimed = false;
            $.each(self.slots(), function(_, slot) {
                $.each(slot.osds(), function(_, osd) {
                    if ([null, undefined].contains(osd.alba_backend_guid()) && osd.processing() === false && slot.processing() === false) {
                        hasUnclaimed = true;
                        return false;
                    }
                });
                if (hasUnclaimed) {
                    return false;
                }
            });
            return hasUnclaimed;
        });
        self.canDelete = ko.pureComputed(function() {
            var deletePossible = true;
            $.each(self.slots(), function(_, slot) {
                if (slot.processing() === true) {
                    deletePossible = false;
                    return false;
                }
                $.each(slot.osds(), function(_, osd) {
                    if ((osd.status() !== 'error' && osd.status() !== 'available') || osd.processing() === true) {
                        deletePossible = false;
                        return false;
                    }
                });
            });
            return deletePossible;
        });
        self.hasStorageRouter = ko.pureComputed(function() {
            var storagerouter_guid = ko.utils.unwrapObservable(self.storagerouter.guid);  // Guid attached to the ViewModel
            return ![null, undefined].contains(self.storagerouter_guid()) && ![null, undefined].contains(storagerouter_guid)
        });

        // Computed factories
        self.canFill = function(slot) {
            return ko.computed(function() {
              // @Todo implement
              return {};
          })
        };
        self.canFillAdd = function(slot) {
            return ko.computed(function() {
              // @Todo implement
              return {};
          })
        };
    }
    var functions = {
        /**
         * Update the current view model with the supplied data
         * Overrules the default update to pull apart stack
         * @param data: Data to update on this view model (keys map with the observables)
         * @type data: Object
         */
        update: function(data) {
            var self = this;
            if ('stack' in data) {
                data = $.extend(data, {'osds': self.generateSlotsByStack()});
            }
            return AlbaNodeBase.prototype.update.call(this, data)
        },
        downloadLogfiles: function () {
            var self = this;
            if (self.downLoadingLogs() === true) {
                return;
            }
            if (generic.xhrCompleted(self.loadLogFilesHandle)) {
                self.downLoadingLogs(true);
                self.downloadLogState($.t('alba:support.downloading_logs'));
                self.loadLogFilesHandle = api.get('alba/nodes/' + self.guid() + '/get_logfiles')
                    .then(self.shared.tasks.wait)
                    .done(function (data) {
                        window.location.href = 'downloads/' + data;
                    })
                    .always(function () {
                        self.downloadLogState($.t('alba:support.download_logs'));
                        self.downLoadingLogs(false);
                    });
            }
        },
        // @Todo fill empty slot again
        fillData: function() {
            var self = this;
            // generic.trySet(self._localSummary, data, 'local_summary');
            // // Add slots
            // var slotIDs = Object.keys(generic.tryGet(data, 'stack', {}));
            // var emptySlotID = undefined;
            // if (self.type() === 'GENERIC') {
            //     if (self.slots().length > 0){
            //         $.each(self.slots().slice(), function(index, slot) {
            //            if (slot.status() === 'empty' && !slotIDs.contains(slot.slotID())){
            //                // Empty slot found in the model of the GUI, let's add it to the stack output
            //                // This way the crossfiller won't remove it
            //                emptySlotID = slot.slotID();
            //                slotIDs.push(emptySlotID);
            //                return false;  // Break
            //            }
            //         });
            //     }
            // }
            // generic.crossFiller(
            //     slotIDs, self.slots,
            //     function(slotID) {
            //         return new Slot(slotID, self, self.albaBackend);
            //     }, 'slotID'
            // );
            // $.each(self.slots(), function (index, slot) {
            //     if (slot.slotID() === emptySlotID) {
            //         // Skip filling the data for the new slot. There is no stack data for it
            //         return true;
            //     }
            //     slot.fillData(data.stack[slot.slotID()])
            // });
            // // No empty slot found, generate one for the future refresh runs
            // if (emptySlotID === undefined && self.type() === 'GENERIC') {
            //     self.generateEmptySlot();
            // }
            // self.slots.sort(function(a, b) {
            //     if ((a.status() === 'empty' && b.status() === 'empty') || (a.status() !== 'empty' && b.status() !== 'empty')) {
            //         return a.slotID() < b.slotID() ? -1 : 1;
            //     } else if (a.status() === 'empty') {  // Move empty status last
            //         return 1;
            //     }
            //     return -1;
            // });
            // self.slotsLoading(false);
            self.loaded(true);
        },
        generateEmptySlot: function() {
            var self = this;
            api.post('alba/nodes/' + self.guid() + '/generate_empty_slot')
                .done(function (data) {
                    self.emptySlotMessage(undefined);
                    var slotID = Object.keys(data)[0];
                    var slot = new Slot(slotID, self, self.albaBackend);
                    slot.fillData(data[slotID]);
                    self.slots.push(slot);
                })
                .fail(function() {
                    self.emptySlotMessage($.t('alba:slots.error_codes.cannot_get_empty'));
                });
        },
        claimAll: function() {
            var self = this;
            if (!self.canClaimAll() || self.read_only_mode() || !self.shared.user.roles().contains('manage')) {
                return;
            }
            var osds = {};
            if (self.albaBackend !== undefined) {
                $.each(self.slots(), function (index, slot) {
                    if (slot.processing()) {
                        return true;
                    }
                    $.each(slot.osds(), function (jndex, osd) {
                        if (![null, undefined].contains(osd.alba_backend_guid()) || osd.processing()) {
                            return true;
                        }
                        if (!osds.hasOwnProperty(slot.slot_id)) {
                            osds[slot.slot_id] = {osds: []};
                        }
                        osds[slot.slot_id].osds.push(osd);
                        if (!osds[slot.slot_id].hasOwnProperty('slot')) {
                            osds[slot.slot_id].slot = slot;
                        }
                    });
                });
            }
            return self.claimOSDs(osds);
        },
        subscribeToSlotEvents: function() {
            var self = this;
            self.disposables.push(  // @Todo for all these events check for possbile relations to throw them to the albanodecluster
                subscriberService.on('albanode_{0}:add_osds'.format([self.node_id()])).then(function (slot) {
                    self.addOSDs(slot);
                }),
                subscriberService.on('albanode_{0}:clear_slot'.format([self.node_id()])).then(function (slot) {
                    self.removeSlot(slot);
                }),
                subscriberService.on('albanode_{0}:claim_osds'.format([self.node_id()])).then(function (data) {
                    self.claimOSDs(data);
                }),
                subscriberService.on('albanode_{0}:restart_osd'.format([self.node_id()])).then(function (osd) {
                    self.restartOSD(osd);
                }),
                subscriberService.on('albanode_{0}:remove_osd'.format([self.node_id()])).then(function (osd) {
                    self.removeOSD(osd);
                }))
        },
        unsubscribeToSlotEvents: function() {
            var self = this;
            self.disposeDisposables()  // Only slot events are registered under disposables for now
        },
        findSlotByOSDID: function(osdID) {
            var self = this;
            return self.slots().find(function(slot){
                return slot.osds().some(function(osd) {
                    return ko.utils.unwrapObservable(osd.osd_id) === osdID
                })
            });
        },
        findSlotBySlotID: function(slotID){
            var self = this;
            return self.slots().find(function(slot){
                return ko.utils.unwrapObservable(slot.slot_id) === slotID
            });
        }
    };
    var wizards = {
        addOSDs: function(slot) {  // Fill the slot specified or all empty Slots if 'slot' is undefined
            var self = this;
            if (!self.canInitializeAll() || self.read_only_mode() || !self.shared.user.roles().contains('manage')) {
                return;
            }
            var slots = [];
            $.each(self.slots(), function(index, currentSlot) {
                if (slot === undefined) {
                    if (currentSlot.osds().length === 0 && currentSlot.processing() === false) {
                        slots.push(currentSlot);
                    }
                } else if (slot.slot_id() === currentSlot.slot_id() && currentSlot.osds().length === 0 && currentSlot.processing() === false) {
                    slots.push(currentSlot);
                }
            });
            var deferred = $.Deferred(),
                wizardCancelled = false,
                wizard = new AddOSDWizard({
                    node: self,
                    slots: slots,
                    modal: true,
                    completed: deferred
                });
            wizard.closing.always(function() {
                wizardCancelled = true;
                deferred.resolve();
            });

            $.each(slots, function(index, slot) {
                slot.processing(true);
                $.each(slot.osds(), function(_, osd) {
                    osd.processing(true);
                });
            });
            dialog.show(wizard);
            deferred.always(function() {
                if (wizardCancelled) {
                    $.each(slots, function(index, slot) {
                        slot.processing(false);
                        $.each(slot.osds(), function(_, osd) {
                            osd.processing(false);
                        });
                    });
                } else {
                    self.parentVM.fetchNodes(false)
                        .then(function() {
                            $.each(slots, function(index, slot) {
                                slot.processing(false);
                                $.each(slot.osds(), function(_, osd) {
                                    osd.processing(false);
                                });
                            });
                        });
                }
            });
        },
        claimOSDs: function(osdsToClaim) {
            var self = this;
            if (self.albaBackend === undefined) {
                return;
            }
            var slots = [];
            var osdData = [];
            var osds = [];
            var resetProcessingState = function() {
                $.each(osds, function(osd) {
                    osd.processing(false);
                });
                $.each(slots, function(slot) {
                    slot.processing(false);
                });
            };
            $.each(osdsToClaim, function(slotID, slotInfo) {
                var slot = self.findSlotBySlotID(slotID);
                slot.processing(true);
                slots.push(slots);
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
                        return api.post('alba/backends/' + self.albaBackend.guid() + '/add_osds', {
                            data: {
                                osds: osdData,
                                alba_node_guid: self.guid()
                            }
                        })
                            .then(self.shared.tasks.wait)
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
                                self.parentVM.fetchNodes(false)
                                    .then(function() {
                                        resetProcessingState();
                                    });
                                deferred.resolve();
                            }, function(error) {
                                error = generic.extractErrorMessage(error);
                                generic.alertError(
                                    $.t('ovs:generic.error'),
                                    $.t('alba:osds.claim.failed', { multi: osdIDs.length === 1 ? '' : 's', why: error })
                                );
                                $.each(osdsToClaim, function(_, slotInfo) {
                                    slotInfo.slot.processing(false);
                                    $.each(slotInfo.osds, function(index, osd) {
                                        osd.processing(false);
                                    });
                                });
                            });
                    } else {
                        resetProcessingState();
                    }
                }, function(error) {
                    resetProcessingState();
                });
        },
        removeOSD: function(osd) {
            var self = this;
            var matchingSlot = self.findSlotByOSDID(osd.osd_id());
            if (matchingSlot === undefined) {
                return;
            }
            var deferred = $.Deferred(),
                wizardCancelled = false,
                wizard = new RemoveOSDWizard({
                    modal: true,
                    albaOSD: osd,
                    albaNode: self,
                    albaSlot: matchingSlot,
                    completed: deferred,
                    albaBackend: self.albaBackend
                });
            wizard.closing.always(function() {
                wizardCancelled = true;
                deferred.resolve();
            });

            osd.processing(true);
            matchingSlot.processing(true);

            dialog.show(wizard);
            deferred.always(function() {
                if (wizardCancelled) {
                    osd.processing(false);
                    matchingSlot.processing(false);
                } else {
                    self.parentVM.fetchNodes(false)
                        .then(function() {
                            osd.processing(false);
                            matchingSlot.processing(false);
                        });
                }
            });
        },
        restartOSD: function(osd) {
            var self = this;
            osd.processing(true);
            generic.alertInfo(
                $.t('alba:osds.restart.started'),
                $.t('alba:osds.restart.started_msg', { what: osd.osdID() })
            );
            return api.post('alba/nodes/' + self.guid() + '/restart_osd', { data: { osd_id: osd.osdID() }})
                .then(self.shared.tasks.wait)
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
            var self = this;
            slot.processing(true);
            $.each(slot.osds(), function(_, osd) {
                osd.processing(true);
            });
            generic.alertInfo(
                $.t('alba:slots.remove.started'),
                $.t('alba:slots.remove.started_msg', { what: slot.slot_id() }));
            (function(currentSlot) {
                return api.post('alba/nodes/' + self.guid() + '/remove_slot', { data: { slot: currentSlot.slot_id() } })
                    .then(self.shared.tasks.wait)
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
                        self.parentVM.fetchNodes(false)
                            .then(function() {
                                currentSlot.processing(false);
                                $.each(currentSlot.osds(), function(_, osd) {
                                    osd.processing(false);
                                });
                            });
                    })
            })(slot);
        },
        deleteNode: function() {
            var self = this;
            if (!self.canDelete() || !self.shared.user.roles().contains('manage')) {
                return;
            }
            app.showMessage(
                $.t('alba:node.remove.warning'),
                $.t('alba:node.remove.title'),
                [$.t('alba:generic.no'), $.t('alba:generic.yes')]
            )
            .done(function(answer) {
                if (answer === $.t('alba:generic.yes')) {
                    $.each(self.slots(), function(index, slot) {
                        slot.processing(true);
                        $.each(slot.osds(), function(jndex, osd) {
                            osd.processing(true);
                        });
                    });
                    return $.Deferred(function(deferred) {
                        generic.alertInfo(
                            $.t('alba:node.remove.started'),
                            $.t('alba:node.remove.started_msg', {what: self.node_id()})
                        );
                        api.del('alba/nodes/' + self.guid())
                            .then(self.shared.tasks.wait)
                            .done(function() {
                                generic.alertSuccess(
                                    $.t('alba:node.remove.complete'),
                                    $.t('alba:node.remove.success', {what: self.node_id()})
                                );
                                deferred.resolve();

                            })
                            .fail(function(error) {
                                error = generic.extractErrorMessage(error);
                                generic.alertError(
                                    $.t('ovs:generic.error'),
                                    $.t('alba:node.remove.failed', {what: self.node_id(), why: error})
                                );
                                deferred.reject();
                            })
                            .always(function() {
                                $.each(self.slots(), function(index, slot) {
                                    slot.processing(false);
                                    $.each(slot.osds(), function(jndex, osd) {
                                        osd.processing(false);
                                    });
                                });
                            });
                    }).promise();
                }
            });
        }
    };
    // Prototypical inheritance
    AlbaNode.prototype = $.extend({}, AlbaNodeBase.prototype, functions, wizards);
    return AlbaNode
});
