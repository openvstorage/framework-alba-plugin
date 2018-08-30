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
    'viewmodels/containers/albanode/albanodebase', 'viewmodels/containers/albanode/albaslot', 'viewmodels/containers/albanode/localsummary',
    'viewmodels/containers/storagerouter/storagerouter',
    'viewmodels/wizards/addosd/index', 'viewmodels/wizards/removeosd/index',
    'viewmodels/services/subscriber', 'viewmodels/services/albabackend', 'viewmodels/services/albanode'
], function($, app, ko, dialog,
            generic, shared,
            AlbaNodeBase, Slot, LocalSummary, StorageRouter,
            AddOSDWizard, RemoveOSDWizard,
            subscriberService, albaBackendService, albaNodeService) {
    "use strict";
    var nodeTypes = {
        generic: 'GENERIC',
        asd: 'ASD',
        s3: 'S3'
    };
    var viewModelMapping = {
        // Avoid caching the same data twice in the mapping plugin. Stack is not required to be observable as we used the slot models instead
        // If stack had to be a viewmodel with observable properties: the slots would need to be created out of a copy of the stack as they now share the same instance
        // If the stack would not just be copied: the plugin would update either the stack or the slots first.
        // Since the slots is derived from the stack data (extracted data using Object.keys), the plugin will have cached the data object
        // (it pumps the full data object into the cache as a key and does a keylookup)
        // When it would update the next property, the plugin would detect that data object to apply was already applied and it won't update the object
        copy: ['stack'],
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
                var data = $.extend(options.data, {
                    node_metadata: options.parent.node_metadata,
                    alba_backend_guid: !!options.parent.albaBackend? ko.utils.unwrapObservable(options.parent.albaBackend.guid) : null
                });
                return new Slot(data);
            }
        }
    };
    var albaBackendDetailContext = 'albaBackendDetail';
    /**
     * AlbaNode class
     * A potential relation with an AlbaNodeCluster is handled by the API. After registering the node under a cluster,
     * the api will treat the node passed as the 'active' side
     * @param albaBackend: Linked Albackend mode
     * @param data: Data that represents this AlbaNode
     * Note: the osds have to be explicitely set to allow the knockout mapping plugin to update them.
     * They can be generated out of the stack property but must be fed in into the data explicitly
     */
    function AlbaNode(data, albaBackend) {
        var self = this;

        AlbaNodeBase.call(this);  // Inherit from Base

        // Variables
        self.shared      = shared;
        self.albaBackend = albaBackend;

        // Handles
        self.loadLogFilesHandle = undefined;
        self.loadingHandle = undefined;

        // Observables
        self.downLoadingLogs   = ko.observable(false);
        self.downloadLogState  = ko.observable($.t('alba:support.download_logs'));
        self.emptySlotMessage  = ko.observable();
        self.expanded          = ko.observable(false);
        self.loaded            = ko.observable(false);
        self._localSummary     = ko.observable();
        self.slotsLoading      = ko.observable(true);
        self.emptySlots        = ko.observableArray([]);

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
            stack: {},
            storagerouter: null,  // Substituted for a viewmodel by the mapping
            storagerouter_guid: null,
            username: null,
            read_only_mode: false,
            type: null
        }, data || {});

        vmData = $.extend(vmData, {'slots': self.generateSlotsByStack(vmData.stack || {})});  // Add slot info
        ko.mapping.fromJS(vmData, viewModelMapping, self);  // Bind the data into this

        if (self.slots().length === 0 && [nodeTypes.generic, nodeTypes.s3].contains(self.type())) {
            self.generateEmptySlot();
        }

        self.loaded(true);

        // Computed
        self.allSlots = ko.pureComputed(function() {  // Include the possible generated empty ones
            return [].concat(self.slots(), self.emptySlots())
        });
        self.emptySlotMapping = ko.pureComputed(function() {
            return self.emptySlots().reduce(function(acc, cur) {
                acc[cur.osd_id] = cur
            }, {});
        });
        self.isPartOfCluster = ko.pureComputed(function() {
           if (self.alba_node_cluster_guid() === undefined) {
               throw new Error('Unable to determine if this node is part of a cluster because the information has not been retrieved')
           }
           return !!self.alba_node_cluster_guid()
        });
        self.canInitializeAll = ko.pureComputed(function() {
            return self.allSlots().some(function(slot) {
                return slot.osds().length === 0 && slot.processing() === false
            });
        });
        self.canClaimAll = ko.pureComputed(function() {
            if (self.albaBackend === undefined) {
                return false;
            }
            return self.allSlots().some(function(slot) {
                return slot.osds().some(function(osd) {
                    return !osd.claimed_by() && !osd.processing() && !slot.processing()
                })
            });
        });
        self.canDelete = ko.pureComputed(function() {
            var deletePossible = true;
            $.each(self.allSlots(), function(_, slot) {
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
        self.displayName = ko.pureComputed(function() {
            if (self.type() === 'GENERIC'){
                if (self.name()) {
                    return self.name()
                }
                return $.t('ovs:generic.null')
            }
            return '{0}:{1}'.format([self.ip(), self.port()])
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
        update: function(data){
            var self = this;
            if ('stack' in data) {
                data = $.extend(data, {'slots': self.generateSlotsByStack(data.stack)});
            }
            return AlbaNodeBase.prototype.update.call(this, data)
        },
        /**
         * Refresh the current instance
         * @param options: Options to refresh with. Defaults to fetching the stack
         */
        refresh: function(options) {
            var self = this;
            if (typeof options === 'undefined') {
                options = { contents: 'stack' }
            }
            return self.loadHandle = albaNodeService.loadAlbaNode(self.guid(), options)
                .then(function(data) {
                    self.update(data);
                    return data
                })
        },
        downloadLogfiles: function () {
            var self = this;
            if (self.downLoadingLogs() === true) {
                return;
            }
            if (generic.xhrCompleted(self.loadLogFilesHandle)) {
                self.downLoadingLogs(true);
                self.downloadLogState($.t('alba:support.downloading_logs'));
                self.loadLogFilesHandle = albaNodeService.downloadLogfiles(self.guid())
                    .done(function (data) {
                        window.location.href = 'downloads/' + data;
                    })
                    .always(function () {
                        self.downloadLogState($.t('alba:support.download_logs'));
                        self.downLoadingLogs(false);
                    });
            }
        },
        generateEmptySlot: function() {
            var self = this;
            return albaNodeService.generateEmptySlot(self.guid())
                .done(function (data) {
                    self.emptySlotMessage(undefined);
                    var slotsData = [];
                    $.each(data, function(key, value){
                        value.slot_id = key;
                        value.node_id = self.node_id();
                        value.node_metadata = self.node_metadata;
                        value.alba_backend_guid = !!self.albaBackend? ko.utils.unwrapObservable(self.albaBackend.guid) : null;
                        slotsData.push(value)
                    });
                    self.emptySlots.push(new Slot(slotsData[0]));
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
            var osds = self.allSlots().reduce(function(result, slot) {
                if (slot.processing()) {
                    return result
                }
                var claimAbleOSDS = slot.osds().filter(function(osd){
                   return (!osd.claimed_by() && !osd.processing())
                });
                if (claimAbleOSDS.length > 0){
                    result[slot.slot_id()] = {osds: claimAbleOSDS};
                }
                return result;
            }, {});
            return self.claimOSDs(osds);
        },
        subscribeToSlotEvents: function() {
            var self = this;
            self.disposables.push(
                subscriberService.onEvents('albanode_{0}:add_osds'.format([self.node_id()]), albaBackendDetailContext).then(function (slot) {
                    self.addOSDs(slot);
                }),
                subscriberService.onEvents('albanode_{0}:clear_slot'.format([self.node_id()]), albaBackendDetailContext).then(function (slot) {
                    self.removeSlot(slot);
                }),
                subscriberService.onEvents('albanode_{0}:claim_osds'.format([self.node_id()]), albaBackendDetailContext).then(function (data) {
                    self.claimOSDs(data);
                }),
                subscriberService.onEvents('albanode_{0}:restart_osd'.format([self.node_id()]), albaBackendDetailContext).then(function (osd) {
                    self.restartOSD(osd);
                }),
                subscriberService.onEvents('albanode_{0}:remove_osd'.format([self.node_id()]), albaBackendDetailContext).then(function (osd) {
                    self.removeOSD(osd);
                }))
        },
        unsubscribeToSlotEvents: function() {
            var self = this;
            self.disposeDisposables()  // Only slot events are registered under disposables for now
        },
        findSlotByOSDID: function(osdID) {
            var self = this;
            return self.allSlots().find(function(slot){
                return slot.osds().some(function(osd) {
                    return ko.utils.unwrapObservable(osd.osd_id) === osdID
                })
            });
        },
        findSlotBySlotID: function(slotID){
            var self = this;
            return self.allSlots().find(function(slot){
                return ko.utils.unwrapObservable(slot.slot_id) === slotID
            });
        }
    };
    var wizards = {
        /**
         * Add new OSDs to the slot
         * Spawns a new 'ADDOSDWizard' to handle the amount to claim
         * @param slot: Slot to add OSDs for
         */
        addOSDs: function(slot) {  // Fill the slot specified or all empty Slots if 'slot' is undefined
            var self = this;
            if (!self.canInitializeAll() || self.read_only_mode() || !self.shared.user.roles().contains('manage')) {
                return;
            }
            var slots = [];
            $.each(self.allSlots(), function(index, currentSlot) {
                if (slot === undefined) {
                    if (currentSlot.osds().length === 0 && currentSlot.processing() === false) {
                        slots.push(currentSlot);
                    }
                } else if (slot.slot_id() === currentSlot.slot_id() && currentSlot.osds().length === 0 && currentSlot.processing() === false) {
                    slots.push(currentSlot);
                }
            });
            var wizard = new AddOSDWizard({
                    node: self,
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
        /**
         * Claims the given OSDs
         * Dual Controller feature has no impact here
         * @param osdsToClaim: Object with slot_id keys and object with a key 'osds', value: list of OSD objects as value
         * @return {Promise<T>}
         */
        claimOSDs: function(osdsToClaim) {
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
            // Dual Controller logic does not change anything about the claiming side
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
        /**
         * Removes an OSD from the backend
         * Spawns a new 'RemoveOSDWizard' to handle the removal
         * @param osd: OSD object to remove
         */
        removeOSD: function(osd) {
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
        /**
         * Restarts an OSD
         * @param osd: OSD object to restart
         * @return {*|void}
         */
        restartOSD: function(osd) {
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
        /**
         * Removes a slot containing OSDs. Clears the OSDs and add new one if the type != GENERIC
         * @param slot: Slot to remove/clear
         */
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
        },
        /**
         * Removes the node from the cluster
         * @return {*}
         */
        deleteNode: function() {
            var self = this;
            if (!self.canDelete() || !self.shared.user.roles().contains('manage')) {
                return $.Deferred(function(deferred){
                    deferred.reject('Unable to delete the node')
                }).promise()
            }
            return app.showMessage(
                $.t('alba:node.remove.warning'),
                $.t('alba:node.remove.title'),
                [$.t('alba:generic.no'), $.t('alba:generic.yes')]
            )
                .then(function(answer) {
                    if (answer !== $.t('alba:generic.yes')) {
                        return null
                    }
                    $.each(self.allSlots(), function(index, slot) {
                        slot.processing(true);
                        $.each(slot.osds(), function(jndex, osd) {
                            osd.processing(true);
                        });
                    });
                    generic.alertInfo(
                        $.t('alba:node.remove.started'),
                        $.t('alba:node.remove.started_msg', {what: self.node_id()})
                    );
                    return albaNodeService.deleteNode(self.guid())
                        .then(function() {
                            generic.alertSuccess(
                                $.t('alba:node.remove.complete'),
                                $.t('alba:node.remove.success', {what: self.node_id()})
                            );
                            subscriberService.trigger('albanode:delete', self)
                        }, function(error) {
                            error = generic.extractErrorMessage(error);
                            generic.alertError(
                                $.t('ovs:generic.error'),
                                $.t('alba:node.remove.failed', {what: self.node_id(), why: error})
                            );
                        })
                        .always(function() {
                            $.each(self.allSlots(), function(index, slot) {
                                slot.processing(false);
                                $.each(slot.osds(), function(jndex, osd) {
                                    osd.processing(false);
                                });
                            });
                        });
                });
        }
    };
    // Prototypical inheritance
    AlbaNode.prototype = $.extend({}, AlbaNodeBase.prototype, functions, wizards);
    return AlbaNode
});
