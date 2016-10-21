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
    'jquery', 'knockout', 'plugins/dialog',
    'ovs/generic', 'ovs/api', 'ovs/shared',
    '../wizards/removeosd/index', '../wizards/initializedisk/index'
], function($, ko, dialog, generic, api, shared, RemoveOSDWizard, InitializeDiskWizard) {
    "use strict";
    return function(nodeID, albaBackend, parent) {
        var self = this;

        // Variables
        self.shared      = shared;
        self.albaBackend = albaBackend;
        self.parent      = parent;

        // External dependencies
        self.storageRouter = ko.observable();

        // Observables
        self.loaded            = ko.observable(false);
        self.guid              = ko.observable();
        self.ip                = ko.observable();
        self.port              = ko.observable();
        self.username          = ko.observable();
        self.nodeID            = ko.observable(nodeID);
        self.storageRouterGuid = ko.observable();
        self.disks             = ko.observableArray([]);
        self.diskNames         = ko.observableArray([]);
        self.ips               = ko.observableArray([]);
        self.expanded          = ko.observable(true);
        self.disksLoading      = ko.observable(true);

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
            var hasUnclaimed = false;
            $.each(self.disks(), function(index, disk) {
                $.each(disk.osds(), function(jndex, osd) {
                    if (osd.status() === 'available' && osd.processing() === false && disk.processing() === false) {
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
                if (disk.status() !== 'error' && disk.status() !== 'uninitialized') {
                    deletePossible = false;
                    return false;
                }
                $.each(disk.osds(), function(jndex, osd) {
                    if (osd.status() !== 'error' && osd.status() !== 'available') {
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
        self.fillData = function(data) {
            self.guid(data.guid);
            self.ip(data.ip);
            self.port(data.port);
            self.username(data.username);
            self.ips(data.ips);
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
        self.initializeDisk = function(disk) {
            dialog.show(new InitializeDiskWizard({
                modal: true,
                disks: [disk],
                node: self
            }));
        };
        self.removeDisk = function(disk) {
            disk.processing(true);
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
        self.claimOSDs = self.albaBackend.claimOSDs;
        self.removeOSD = function(asd) {
            var matchingDisk = undefined;
            $.each(self.disks(), function(index, disk) {
                $.each(disk.osds(), function(_, osd) {
                    if (osd.osdID() === asd.osdID()) {
                        matchingDisk = disk;
                        return false;
                    }
                });
                if (matchingDisk !== undefined) {
                    return false;
                }
            });
            if (matchingDisk !== undefined) {
                matchingDisk.processing(true);
            }
            dialog.show(new RemoveOSDWizard({
                modal: true,
                albaBackend: self.albaBackend,
                albaNode: self,
                albaOSD: asd,
                albaDisk: matchingDisk
            }));
        };
        self.initializeAll = function() {
            var disks = [];
            $.each(self.disks(), function(index, disk) {
                if (disk.status() === 'uninitialized') {
                    disks.push(disk);
                }
            });
            dialog.show(new InitializeDiskWizard({
                modal: true,
                disks: disks,
                node: self
            }));
        };
        self.claimAll = function() {
            var asds = {};
            $.each(self.disks(), function(index, disk) {
                asds[disk.guid()] = [];
                if (disk.processing()) {
                    return true;
                }
                $.each(disk.osds(), function (jndex, asd) {
                    if (asd.status() !== 'available' || asd.processing()) {
                        return true;
                    }
                    asds[disk.guid()].push(asd);
                });
            });
            return self.albaBackend.claimOSDs(asds);
        };
        self.deleteNode = function() {
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
        };
        self.restartOSD = function(asd) {
            asd.processing(true);
            return $.Deferred(function(deferred) {
                generic.alertInfo(
                    $.t('alba:osds.restart.started'),
                    $.t('alba:osds.restart.started_msg', {what: asd.osdID()})
                );
                api.post('alba/nodes/' + self.guid() + '/restart_asd', {
                    data: { asd_id: asd.osdID() }
                })
                    .then(self.shared.tasks.wait)
                    .done(function() {
                        generic.alertSuccess(
                            $.t('alba:osds.restart.complete'),
                            $.t('alba:osds.restart.success', {what: asd.osdID()})
                        );
                        deferred.resolve();

                    })
                    .fail(function(error) {
                        error = generic.extractErrorMessage(error);
                        generic.alertError(
                            $.t('ovs:generic.error'),
                            $.t('alba:osds.restart.failed', {what: asd.osdID(), why: error})
                        );
                        deferred.reject();
                    })
                    .always(function() {
                        asd.processing(false);
                    });
            }).promise();
        };
    };
});
