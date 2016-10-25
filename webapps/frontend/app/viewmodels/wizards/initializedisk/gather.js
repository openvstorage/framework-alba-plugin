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
    'jquery', 'knockout',
    'ovs/api', 'ovs/shared', 'ovs/generic',
    './data'
], function($, ko, api, shared, generic, data) {
    "use strict";
    return function() {
        var self = this;

        // Variables
        self.data   = data;
        self.shared = shared;

        // Computed
        self.canContinue = ko.computed(function() {
            return { value: true, reasons: [], fields: [] };
        });

        self.finish = function() {
            return $.Deferred(function(deferred) {
                var disks = [];
                $.each(self.data.disks(), function(index, disk) {
                    disks.push(disk);
                });
                if (disks.length === 1) {
                    generic.alertInfo(
                        $.t('alba:disks.initialize.started'),
                        $.t('alba:disks.initialize.started_msg_single', {what: disks[0].device()})
                    );
                } else {
                    generic.alertInfo(
                        $.t('alba:disks.initialize.started'),
                        $.t('alba:disks.initialize.started_msg_multi')
                    );
                }
                (function(disks, amount, nodeGuid, dfd) {
                    var diskData = {}, aliasDeviceNameMap = {};
                    $.each(disks, function(index, disk) {
                        disk.processing(true);
                        if (disk.aliases() !== undefined) {
                            $.each(disk.aliases(), function(index, alias) {
                                aliasDeviceNameMap[alias] = disk.device();
                            });
                        }
                        diskData[disk.alias()] = amount;
                    });
                    api.post('alba/nodes/' + nodeGuid + '/initialize_disks', {
                        data: { disks: diskData }
                    })
                        .then(self.shared.tasks.wait)
                        .done(function(failures) {
                            if (generic.keys(failures).length > 0) {
                                if (disks.length === 1) {
                                    var key = generic.keys(failures)[0];
                                    generic.alertError(
                                        $.t('ovs:generic.error'),
                                        $.t('alba:disks.initialize.failed_single', {what: disks[0].device(), why: failures[key]})
                                    );
                                } else {
                                    var error = '\n';
                                    $.each(failures, function(alias, message) {
                                        if (aliasDeviceNameMap.hasOwnProperty(alias)) {
                                            error += aliasDeviceNameMap[alias] + ': ' + message + '\n';
                                        } else {
                                            error += alias + ': ' + message + '\n';
                                        }
                                    });
                                    generic.alertError(
                                        $.t('ovs:generic.error'),
                                        $.t('alba:disks.initialize.failed_multi', {why: error})
                                    );
                                }
                                $.each(disks, function(index, disk) {
                                    disk.processing(false);
                                });
                            } else {
                                $.each(disks, function(index, disk) {
                                    disk.ignoreNext(true);
                                    disk.status('initialized');
                                    disk.processing(false);
                                });
                                if (disks.length === 1) {
                                    generic.alertSuccess(
                                        $.t('alba:disks.initialize.complete'),
                                        $.t('alba:disks.initialize.success_single', {what: disks[0].device()})
                                    );
                                } else {
                                    generic.alertSuccess(
                                        $.t('alba:disks.initialize.complete'),
                                        $.t('alba:disks.initialize.success_multi')
                                    );
                                }
                            }
                        })
                        .fail(function(error) {
                            $.each(disks, function(index, disk) {
                                disk.processing(false);
                            });
                            error = generic.extractErrorMessage(error);
                            generic.alertError(
                                $.t('ovs:generic.error'),
                                $.t('alba:disks.initialize.failed_multi', { why: error })
                            );
                        });
                    dfd.resolve();
                })(disks, self.data.amount(), self.data.node().guid(), deferred);
            }).promise();
        };
    };
});
