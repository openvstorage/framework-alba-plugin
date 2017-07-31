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
    '../wizards/removeosd/index',
    '../containers/albaslot'
], function($, app, ko, dialog,
            generic, api, shared,
            RemoveOSDWizard,
            Slot) {
    "use strict";
    return function(nodeID, albaBackend, parentVM) {
        var self = this;

        // Variables
        self.shared      = shared;
        self.albaBackend = albaBackend;
        self.parentVM    = parentVM;  // Parent ViewModel, so backend-alba-detail page in this case

        // Handles
        self.loadLogFilesHandle = undefined;

        // External dependencies
        self.storageRouter = ko.observable();

        // Observables
        self.diskNames         = ko.observableArray([]);
        self.disks             = ko.observableArray([]);  // @todo add asds related to disks to osds and replace disks with slots
        self.downLoadingLogs   = ko.observable(false);
        self.downloadLogState  = ko.observable($.t('alba:support.download_logs'));
        self.expanded          = ko.observable(true);
        self.guid              = ko.observable();
        self.ip                = ko.observable();
        self.ips               = ko.observableArray([]);
        self.loaded            = ko.observable(false);
        self.name              = ko.observable();
        self.nodeID            = ko.observable(nodeID);
        self.nodeMetadata      = ko.observable();
        self.osds              = ko.observableArray([]);
        self.port              = ko.observable();
        self.readOnlyMode      = ko.observable(false);
        self.slots             = ko.observableArray([]);
        self.slotsLoading      = ko.observable(true);
        self.storageRouterGuid = ko.observable();
        self.type              = ko.observable();
        self.username          = ko.observable();

        // Computed
        self.canClaimAll = ko.computed(function() {
            if (self.albaBackend === undefined) {
                return false;
            }
            var hasUnclaimed = false;
            $.each(self.slots(), function(index, slot) {
                $.each(slot.osds(), function(jndex, osd) {
                    if (osd.albaBackendGuid() === undefined && osd.processing() === false && slot.processing() === false) {
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
        self.canDelete = ko.computed(function() {
            var deletePossible = true;
            $.each(self.disks(), function(index, disk) {
                if ((disk.status() !== 'error' && disk.status() !== 'uninitialized') || disk.processing() === true) {
                    deletePossible = false;
                    return false;
                }
                $.each(disk.osds(), function(jndex, osd) {
                    if ((osd.status() !== 'error' && osd.status() !== 'available') || osd.processing() === true) {
                        deletePossible = false;
                        return false;
                    }
                });
                if (deletePossible === false) {
                    return false;
                }
            });
            return deletePossible;
        });
        
        // Functions
        self.downloadLogfiles = function () {
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
        };
        self.fillData = function(data) {
            self.ip(data.ip);
            self.guid(data.guid);
            self.name(data.name);
            self.port(data.port);
            self.type(data.type);
            self.username(data.username);
            generic.trySet(self.ips, data, 'ips');
            generic.trySet(self.nodeMetadata, data, 'node_metadata');
            generic.trySet(self.readOnlyMode, data, 'read_only_mode');
            generic.trySet(self.storageRouterGuid, data, 'storagerouter_guid');
            
            // Add slots
            var slotIds = Object.keys(data.stack);
            generic.crossFiller(
                slotIds, self.slots,
                function(slotId) {
                    return new Slot(slotId, self, self.albaBackend);
                }, 'slotId'
            );
            $.each(self.slots(), function (index, slot) {
                slot.fillData(data.stack[slot.slotId()])
            });
            self.slots.sort(function(a, b) {
                return a.slotId() < b.slotId() ? -1 : 1
            });
            self.slotsLoading(false);
            self.loaded(true);
        };
        self.claimAll = function() {
            if (self.readOnlyMode()) {
                return;
            }
            var osds = {};
            if (self.albaBackend !== undefined) {
                $.each(self.slots(), function (index, slot) {
                    osds[slot.slotId()] = [];
                    if (slot.processing()) {
                        return true;
                    }
                    $.each(slot.osds(), function (jndex, osd) {
                        if (osd.albaBackendGuid() !== undefined || osd.processing()) {
                            return true;
                        }
                        osds[slot.slotId()].push(osd);
                    });
                });
            }
            return self.albaBackend.claimOSDs(osds, self.guid());
        };
        self.claimOSDs = self.albaBackend !== undefined ? self.albaBackend.claimOSDs : undefined;
        self.removeOSD = function(asd) {
            var matchingSlot = undefined;
            $.each(self.slots(), function(index, slot) {
                $.each(slot.osds(), function(_, osd) {
                    if (osd.osdID() === asd.osdID()) {
                        matchingSlot = slot;
                        return false;
                    }
                });
                if (matchingSlot !== undefined) {
                    return false;
                }
            });
            dialog.show(new RemoveOSDWizard({
                modal: true,
                albaBackend: self.albaBackend,
                albaNode: self,
                albaOSD: asd,
                albaSlot: matchingSlot
            }));
        };
        self.restartOSD = function(osd) {
            osd.processing(true);
            return $.Deferred(function(deferred) {
                generic.alertInfo(
                    $.t('alba:osds.restart.started'),
                    $.t('alba:osds.restart.started_msg', {what: osd.osdID()})
                );
                api.post('alba/nodes/' + self.guid() + '/restart_osd', {
                    data: { osd_id: osd.osdID() }
                })
                    .then(self.shared.tasks.wait)
                    .done(function() {
                        generic.alertSuccess(
                            $.t('alba:osds.restart.complete'),
                            $.t('alba:osds.restart.success', {what: osd.osdID()})
                        );
                        deferred.resolve();

                    })
                    .fail(function(error) {
                        error = generic.extractErrorMessage(error);
                        generic.alertError(
                            $.t('ovs:generic.error'),
                            $.t('alba:osds.restart.failed', {what: osd.osdID(), why: error})
                        );
                        deferred.reject();
                    })
                    .always(function() {
                        osd.processing(false);
                    });
            }).promise();
        };
        self.removeSlot = function(slot) {
            slot.processing(true);
            $.each(slot.osds(), function(_, osd) {
                osd.processing(true);
            });
            return $.Deferred(function(deferred) {
                generic.alertInfo(
                    $.t('alba:slots.remove.started'),
                    $.t('alba:slots.remove.started_msg', {what: slot.slotId()})
                );
                (function(currentSlot, dfd) {
                    api.post('alba/nodes/' + self.guid() + '/remove_slot', {
                        data: { slot: currentSlot.slotId() }
                    })
                        .then(self.shared.tasks.wait)
                        .done(function() {
                            generic.alertSuccess(
                                $.t('alba:slots.remove.complete'),
                                $.t('alba:slots.remove.success', {what: currentSlot.slotId()})
                            );
                            dfd.resolve();
                        })
                        .fail(function(error) {
                            error = generic.extractErrorMessage(error);
                            generic.alertError(
                                $.t('ovs:generic.error'),
                                $.t('alba:slots.remove.failed', {what: currentSlot.slotId(), why: error})
                            );
                            dfd.reject();
                        })
                        .always(function() {
                            currentSlot.processing(false);
                            $.each(currentSlot.osds(), function(_, osd) {
                                osd.processing(false);
                            });
                            self.parentVM.fetchNodes(false);
                        })
                })(slot, deferred);
            }).promise();
        };
        self.deleteNode = function() {
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
                            $.t('alba:node.remove.started_msg', {what: self.nodeID()})
                        );
                        api.del('alba/nodes/' + self.guid())
                            .then(self.shared.tasks.wait)
                            .done(function() {
                                generic.alertSuccess(
                                    $.t('alba:node.remove.complete'),
                                    $.t('alba:node.remove.success', {what: self.nodeID()})
                                );
                                deferred.resolve();

                            })
                            .fail(function(error) {
                                error = generic.extractErrorMessage(error);
                                generic.alertError(
                                    $.t('ovs:generic.error'),
                                    $.t('alba:node.remove.failed', {what: self.nodeID(), why: error})
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
        };
    };
});
