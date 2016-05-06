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
    'jquery', 'knockout', 'durandal/app', 'plugins/dialog',
    'ovs/generic', 'ovs/api', 'ovs/shared',
    '../containers/albaosd', '../wizards/addalbanode/index', '../wizards/removeosd/index',
    '../wizards/initializedisk/index'
], function($, ko, app, dialog, generic, api, shared, OSD, AddAlbaNodeWizard, RemoveOSDWizard, InitializeDiskWizard) {
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
        self.canClaimAll      = ko.computed(function() {
            var hasUnclaimed = false;
            $.each(self.disks(), function(index, disk) {
                $.each(disk.asds(), function(jndex, asd) {
                    if (asd.status() === 'available' && asd.processing() === false) {
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
        self.register = function() {
            dialog.show(new AddAlbaNodeWizard({
                modal: true,
                node: self
            }));
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
                generic.alertSuccess(
                    $.t('alba:disks.remove.started'),
                    $.t('alba:disks.remove.msgstarted')
                );
                api.post('alba/nodes/' + self.guid() + '/remove_disk', {
                    data: { disk: disk.name() }
                })
                    .then(self.shared.tasks.wait)
                    .done(function() {
                        generic.alertSuccess(
                            $.t('alba:disks.remove.complete'),
                            $.t('alba:disks.remove.success')
                        );
                        deferred.resolve();
                        disk.ignoreNext(true);
                        disk.status('uninitialized');
                        disk.processing(false);
                    })
                    .fail(function(error) {
                        generic.alertError(
                            $.t('ovs:generic.error'),
                            $.t('alba:disks.remove.failed', { why: error })
                        );
                        deferred.reject();
                        disk.processing(false);
                    });
            }).promise();
        };
        self.restartDisk = function(disk) {
            disk.processing(true);
            return $.Deferred(function(deferred) {
                generic.alertSuccess(
                    $.t('alba:disks.restart.started'),
                    $.t('alba:disks.restart.msgstarted')
                );
                api.post('alba/nodes/' + self.guid() + '/restart_disk', {
                    data: { disk: disk.name() }
                })
                    .then(self.shared.tasks.wait)
                    .done(function() {
                        generic.alertSuccess(
                            $.t('alba:disks.restart.complete'),
                            $.t('alba:disks.restart.success')
                        );
                        deferred.resolve();
                        disk.processing(false);
                    })
                    .fail(function(error) {
                        generic.alertError(
                            $.t('ovs:generic.error'),
                            $.t('alba:disks.restart.failed', { why: error })
                        );
                        deferred.reject();
                        disk.processing(false);
                    });
            }).promise();
        };
        self.claimOSDs = self.albaBackend.claimOSDs;
        self.removeOSD = function(asd) {
            dialog.show(new RemoveOSDWizard({
                modal: true,
                albaBackend: self.albaBackend,
                albaNode: self,
                albaOSD: asd
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
                $.each(disk.asds(), function (jndex, asd) {
                    if (asd.status() !== 'available' || asd.processing()) {
                        return true;
                    }
                    asds[disk.guid()].push(asd);
                });
            });
            return self.albaBackend.claimOSDs(asds);
        };
        self.restartOSD = function(asd) {
            asd.processing(true);
            return $.Deferred(function(deferred) {
                generic.alertSuccess(
                    $.t('alba:disks.restart.started'),
                    $.t('alba:disks.restart.msgstarted')
                );
                api.post('alba/nodes/' + self.guid() + '/restart_asd', {
                    data: { asd_id: asd.asdID() }
                })
                    .then(self.shared.tasks.wait)
                    .done(function() {
                        generic.alertSuccess(
                            $.t('alba:disks.restart.complete'),
                            $.t('alba:disks.restart.success')
                        );
                        deferred.resolve();

                    })
                    .fail(function(error) {
                        generic.alertError(
                            $.t('ovs:generic.error'),
                            $.t('alba:disks.restart.failed', { why: error })
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
