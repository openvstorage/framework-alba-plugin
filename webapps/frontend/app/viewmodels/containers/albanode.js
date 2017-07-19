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
        self.parentVM    = parentVM;

        // Handles
        self.loadLogFilesHandle = undefined;

        // External dependencies
        self.storageRouter = ko.observable();

        // Observables
        self.diskNames         = ko.observableArray([]);
        self.disks             = ko.observableArray([]);  // @todo add asds related to disks to osds and replace disks with slots
        self.disksLoading      = ko.observable(true);  // @todo only use slotsloading
        self.downLoadingLogs   = ko.observable(false);
        self.downloadLogState  = ko.observable($.t('alba:support.download_logs'));
        self.expanded          = ko.observable(true);
        self.guid              = ko.observable();
        self.ip                = ko.observable();
        self.ips               = ko.observableArray([]);
        self.loaded            = ko.observable(false);
        self.name              = ko.observable();
        self.nodeMetadata      = ko.observable();
        self.nodeID            = ko.observable(nodeID);
        self.port              = ko.observable();
        self.storageRouterGuid = ko.observable();
        self.username          = ko.observable();
        self.osds              = ko.observableArray([]);
        self.slots             = ko.observableArray([]);
        self.slotsLoading      = ko.observable(true);
        self.type              = ko.observable();

        // Computed
        self.canInitializeAll = ko.computed(function() {
            var hasUninitialized = false;
            $.each(self.disks(), function(index, disk) {
                if (disk.status() === 'uninitialized' && disk.processing() === false) {
                    hasUninitialized = true;
                    return false;
                }
            });
            return hasUninitialized;
        });
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
            self.guid(data.guid);
            self.ip(data.ip);
            self.port(data.port);
            self.username(data.username);
            self.ips(data.ips);
            self.type(data.type);
            self.nodeMetadata(data.node_metadata);
            generic.trySet(self.name, data, 'name');
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
                // An empty slot should always be at the last point
                if (!(a.status() === 'empty' && b.status() === 'empty') && (a.status() === 'empty' || b.status() === 'empty')) {
                    return a.status() === 'empty' ? 1 : -1;
                }
                return a.slotId() < b.slotId() ? -1 : 1
            });
            self.slotsLoading(false);
            generic.trySet(self.storageRouterGuid, data, 'storagerouter_guid');
            self.loaded(true);
        };
        self.highlight = function(status, highlight) {
            $.each(self.disks(), function(index, disk) {
                if (disk.status() === status && (!highlight || disk.processing() === false)) {
                    disk.highlighted(highlight);
                }
            });
        };
        self.removeDisk = function(disk) {
            disk.processing(true);
            $.each(disk.osds(), function(_, osd) {
                osd.processing(true);
            });
            return $.Deferred(function(deferred) {
                generic.alertInfo(
                    $.t('alba:disks.remove.started'),
                    $.t('alba:disks.remove.started_msg', {what: disk.device() === undefined ? '' : disk.device()})
                );
                api.post('alba/nodes/' + self.guid() + '/remove_disk', {
                    data: { disk: disk.alias() }
                })
                    .then(self.shared.tasks.wait)
                    .done(function() {
                        generic.alertSuccess(
                            $.t('alba:disks.remove.complete'),
                            $.t('alba:disks.remove.success', {what: disk.device() === undefined ? '' : disk.device()})
                        );
                        deferred.resolve();
                        disk.ignoreNext(true);
                        disk.status('uninitialized');
                        disk.processing(false);
                    })
                    .fail(function(error) {
                        error = generic.extractErrorMessage(error);
                        generic.alertError(
                            $.t('ovs:generic.error'),
                            $.t('alba:disks.remove.failed', {what: disk.device() === undefined ? '' : disk.device(), why: error})
                        );
                        deferred.reject();
                        disk.processing(false);
                    });
            }).promise();
        };
        self.restartDisk = function(disk) {
            disk.processing(true);
            $.each(disk.osds(), function(_, osd) {
                osd.processing(true);
            });
            return $.Deferred(function(deferred) {
                generic.alertInfo(
                    $.t('alba:disks.restart.started'),
                    $.t('alba:disks.restart.started_msg', {what: disk.device() === undefined ? '' : disk.device()})
                );
                api.post('alba/nodes/' + self.guid() + '/restart_disk', {
                    data: { disk: disk.alias() }
                })
                    .then(self.shared.tasks.wait)
                    .done(function() {
                        generic.alertSuccess(
                            $.t('alba:disks.restart.complete'),
                            $.t('alba:disks.restart.success', {what: disk.device() === undefined ? '' : disk.device()})
                        );
                        deferred.resolve();
                        disk.processing(false);
                    })
                    .fail(function(error) {
                        error = generic.extractErrorMessage(error);
                        generic.alertError(
                            $.t('ovs:generic.error'),
                            $.t('alba:disks.restart.failed', {what: disk.device() === undefined ? '' : disk.device(), why: error})
                        );
                        deferred.reject();
                        disk.processing(false);
                    });
            }).promise();
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
        self.claimAll = function() {
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
            return self.albaBackend.claimOSDs(osds);
        };
        self.deleteNode = function() {
            app.showMessage(
                $.t('alba:node.remove.warning'),
                $.t('alba:node.remove.title'),
                [$.t('alba:generic.no'), $.t('alba:generic.yes')]
            )
            .done(function(answer) {
                if (answer === $.t('alba:generic.yes')) {
                    $.each(self.disks(), function(index, disk) {
                        disk.processing(true);
                        $.each(disk.osds(), function(jndex, osd) {
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
                                $.each(self.disks(), function(index, disk) {
                                    disk.processing(false);
                                    $.each(disk.osds(), function(jndex, osd) {
                                        osd.processing(false);
                                    });
                                });
                            });
                    }).promise();
                }
            });
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
    };
});
