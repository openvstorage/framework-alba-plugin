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
    'ovs/api', 'ovs/generic', 'ovs/shared', 'ovs/refresher', './data'
], function($, ko, api, generic, shared, Refresher, data) {
    "use strict";
    return function(parent) {
        var self = this;

        // Variables
        self.shared    = shared;
        self.refresher = new Refresher();
        self.data      = data;

        // Computed
        self.canContinue = ko.computed(function() {
            var valid = (!self.data.shouldConfirm() || self.data.confirmed()) && self.data.loaded();
            return { value: valid, reasons: [], fields: [] };
        });

        // Functions
        self.finish = function() {
            self.data.albaOSD().processing(true);
            return $.Deferred(function(deferred) {
                generic.alertSuccess(
                    $.t('alba:disks.remove.started'),
                    $.t('alba:disks.remove.msgstarted')
                );
                api.post('alba/nodes/' + self.data.albaNode().guid() + '/reset_asd', {
                    data: {
                        asd_id: self.data.albaOSD().asdID(),
                        safety: self.data.safety()
                    }
                })
                    .then(self.shared.tasks.wait)
                    .done(function() {
                        generic.alertSuccess(
                            $.t('alba:disks.remove.complete'),
                            $.t('alba:disks.remove.success')
                        );
                    })
                    .fail(function(error) {
                        generic.alertError(
                            $.t('ovs:generic.error'),
                            $.t('alba:disks.remove.failed', { why: error })
                        );
                    })
                    .always(function() {
                        self.data.albaOSD().processing(false);
                    });
                deferred.resolve();
            }).promise();
        };

        // Durandal
        self.activate = function() {
            self.refresher.init(function() {
                api.get('alba/backends/' + self.data.albaBackend().guid() + '/calculate_safety', {
                    queryparams: { asd_id: self.data.albaOSD().asdID() }
                })
                    .then(self.shared.tasks.wait)
                    .done(function(safety) {
                        self.data.safety(safety);
                        self.data.loaded(true);
                    });
            }, 5000);
            self.refresher.run();
            self.refresher.start();
            parent.closing.always(function() {
                self.refresher.stop();
                self.data.albaOSD().processing(false);
            });
            parent.finishing.always(function() {
                self.refresher.stop();
            });
        };
    };
});
