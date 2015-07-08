// Copyright 2014 Open vStorage NV
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
            var valid = true, reasons = [], fields = [];
            if (self.data.username() === undefined || self.data.username() === '') {
                valid = false;
                fields.push('username');
                reasons.push($.t('ovs:wizards.addmgmtcenter.gather.nousername'));
            }
            if (self.data.password() === undefined || self.data.password() === '') {
                valid = false;
                fields.push('password');
                reasons.push($.t('ovs:wizards.addmgmtcenter.gather.nopassword'));
            }
            return { value: valid, reasons: reasons, fields: fields };
        });

        // Functions
        self.finish = function() {
            return $.Deferred(function(deferred) {
                generic.alertInfo(
                    $.t('alba:wizards.addalbanode.gather.started'),
                    $.t('alba:wizards.addalbanode.gather.inprogress')
                );
                deferred.resolve();
                api.post('alba/nodes', {
                    data: {
                        box_id: self.data.node().boxID(),
                        ip: self.data.node().ip(),
                        port: self.data.node().port(),
                        username: self.data.username(),
                        password: self.data.password(),
                        asd_ips: self.data.ips()
                    }
                })
                    .then(self.shared.tasks.wait)
                    .done(function() {
                        generic.alertSuccess(
                            $.t('alba:wizards.addalbanode.gather.complete'),
                            $.t('alba:wizards.addalbanode.gather.success')
                        );
                    })
                    .fail(function(error) {
                        generic.alertError(
                            $.t('ovs:generic.error'),
                            $.t('alba:wizards.addalbanode.gather.failed', {
                                why: error
                            })
                        );
                    });
            }).promise();
        };
    };
});
