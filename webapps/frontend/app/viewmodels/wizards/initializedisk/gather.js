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
                generic.alertInfo(
                    $.t('alba:disks.initialize.started'),
                    $.t('alba:disks.initialize.msgstarted')
                );
                var disks = [];
                $.each(self.data.disks(), function(index, disk) {
                    disks.push(disk);
                });
                (function(disks, amount, nodeGuid, dfd) {
                    var disk_data = {};
                    $.each(disks, function(index, disk) {
                        disk.processing(true);
                        disk_data[disk.name()] = amount;
                    });
                    api.post('alba/nodes/' + nodeGuid + '/initialize_disks', {
                        data: { disks: disk_data }
                    })
                        .then(self.shared.tasks.wait)
                        .done(function(failures) {
                            if (generic.keys(failures).length > 0) {
                                var error = '';
                                $.each(failures, function(disk, message) {
                                    error = message;
                                });
                                $.each(disks, function(index, disk) {
                                    disk.processing(false);
                                });
                                generic.alertError(
                                    $.t('ovs:generic.error'),
                                    $.t('alba:disks.initialize.failed', { why: error })
                                );
                            } else {
                                $.each(disks, function(index, disk) {
                                    disk.ignoreNext(true);
                                    disk.status('initialized');
                                    disk.processing(false);
                                });
                                generic.alertSuccess(
                                    $.t('alba:disks.initialize.complete'),
                                    $.t('alba:disks.initialize.success')
                                );
                            }
                        })
                        .fail(function(error) {
                            $.each(disks, function(index, disk) {
                                disk.processing(false);
                            });
                            generic.alertError(
                                $.t('ovs:generic.error'),
                                $.t('alba:disks.initialize.failed', { why: error })
                            );
                        });
                    dfd.resolve();
                })(disks, self.data.amount(), self.data.node().guid(), deferred);
            }).promise();
        };
    };
});
