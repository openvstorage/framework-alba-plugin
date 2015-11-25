// Copyright 2014 iNuron NV
//
// Licensed under the Open vStorage Modified Apache License (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.openvstorage.org/license
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
    '../containers/albaosd', '../wizards/addalbanode/index', '../wizards/removeosd/index'
], function($, ko, app, dialog, generic, api, shared, OSD, AddAlbaNodeWizard, RemoveOSDWizard) {
    "use strict";
    return function(nodeID, parent) {
        var self = this;

        // Variables
        self.shared  = shared;
        self.parent = parent;

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
        self.ips               = ko.observableArray([]);
        self.expanded          = ko.observable(true);

        // Computed
        self.diskRows         = ko.splitRows(3, self.disks);
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
                if (disk.status() === 'available' && disk.processing() === false) {
                    hasUnclaimed = true;
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
        self.initializeNode = function(disk) {
            return $.Deferred(function(deferred) {
                generic.alertSuccess(
                    $.t('alba:disks.initialize.started'),
                    $.t('alba:disks.initialize.msgstarted')
                );
                api.post('alba/nodes/' + self.guid() + '/initialize_disks', {
                    data: { disks: [disk] }
                })
                    .then(self.shared.tasks.wait)
                    .done(function(failures) {
                        if (generic.keys(failures).length > 0) {
                            var error = '';
                            $.each(failures, function(disk, message) {
                                error = message;
                            });
                            generic.alertError(
                                $.t('ovs:generic.error'),
                                $.t('alba:disks.initialize.failed', { why: error })
                            );
                            deferred.reject();
                        } else {
                            generic.alertSuccess(
                                $.t('alba:disks.initialize.complete'),
                                $.t('alba:disks.initialize.success')
                            );
                            deferred.resolve();
                        }
                    })
                    .fail(function(error) {
                        generic.alertError(
                            $.t('ovs:generic.error'),
                            $.t('alba:disks.initialize.failed', { why: error })
                        );
                        deferred.reject();
                    });
            }).promise();
        };
        self.restartOSD = function(disk) {
            return $.Deferred(function(deferred) {
                generic.alertSuccess(
                    $.t('alba:disks.restart.started'),
                    $.t('alba:disks.restart.msgstarted')
                );
                api.post('alba/nodes/' + self.guid() + '/restart_disk', {
                    data: { disk: disk }
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
                    });
            }).promise();
        };
        self.removeOSD = function(osd) {
            dialog.show(new RemoveOSDWizard({
                modal: true,
                albaOSD: osd,
                albaNode: self,
                albaBackend: self.parent.albaBackend()
            }));
        };
        self.claimOSD = self.parent.claimOSD;
        self.initializeAll = function() {
            return $.Deferred(function(deferred) {
                app.showMessage(
                    $.t('alba:disks.initializeall.warning'),
                    $.t('ovs:generic.areyousure'),
                    [$.t('ovs:generic.no'), $.t('ovs:generic.yes')]
                )
                    .done(function(answer) {
                        if (answer === $.t('ovs:generic.yes')) {
                            generic.alertSuccess(
                                $.t('alba:disks.initializeall.started'),
                                $.t('alba:disks.initializeall.msgstarted')
                            );
                            var diskNames = [];
                            $.each(self.disks(), function(index, disk) {
                                if (disk.status() === 'uninitialized' && disk.processing() === false) {
                                    disk.processing(true);
                                    diskNames.push(disk.name());
                                }
                            });
                            api.post('alba/nodes/' + self.guid() + '/initialize_disks', {
                                data: { disks: diskNames }
                            })
                                .then(self.shared.tasks.wait)
                                .done(function(failures) {
                                    if (generic.keys(failures).length > 0) {
                                        var errors = [];
                                        $.each(failures, function(disk, message) {
                                            errors.push(disk + ': ' + message);
                                        });
                                        generic.alertInfo(
                                            $.t('alba:disks.initializeall.complete'),
                                            $.t('alba:disks.initializeall.somefailed', { which: '<ul><li>' + errors.join('</li><li>') + '</li></ul>' })
                                        );
                                        deferred.resolve();
                                    } else {
                                        $.each(self.disks(), function(index, disk) {
                                            if ($.inArray(disk.name(), diskNames) !== -1) {
                                                disk.ignoreNext(true);
                                                if (disk.status() === 'uninitialized') {
                                                    disk.status('initialized');
                                                }
                                            }
                                        });
                                        generic.alertSuccess(
                                            $.t('alba:disks.initializeall.complete'),
                                            $.t('alba:disks.initializeall.success')
                                        );
                                        deferred.resolve();
                                    }
                                })
                                .fail(function(error) {
                                    generic.alertError(
                                        $.t('ovs:generic.error'),
                                        $.t('alba:disks.initializeall.failed', { why: error })
                                    );
                                    deferred.reject();
                                })
                                .always(function() {
                                    $.each(self.disks(), function(index, disk) {
                                        if ($.inArray(disk.name(), diskNames) !== -1) {
                                            disk.processing(false);
                                        }
                                    });
                                });
                        } else {
                            deferred.reject();
                        }
                    });
            }).promise();
        };
        self.claimAll = function() {
            return $.Deferred(function(deferred) {
                var osds = {}, disks = [];
                $.each(self.disks(), function(index, disk) {
                    if (disk.status() === 'available' && disk.processing() === false) {
                        disk.processing(true);
                        disks.push(disk.name());
                        osds[disk.asdID()] = disk.node.guid();
                    }
                });
                self.parent.claimAll(osds, disks)
                    .done(function() {
                        $.each(self.disks(), function(index, disk) {
                            if ($.inArray(disk.name(), disks) !== -1) {
                                disk.ignoreNext(true);
                                if (disk.status() === 'available') {
                                    disk.status('claimed');
                                }
                            }
                        });
                    })
                    .always(function() {
                        $.each(self.disks(), function(index, disk) {
                            if ($.inArray(disk.name(), disks) !== -1) {
                                disk.processing(false);
                            }
                        });
                        deferred.resolve();
                    });
            }).promise();
        };
    };
});
