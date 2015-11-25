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
    'jquery', 'knockout',
    'ovs/api', 'ovs/shared', 'ovs/generic',
    './data'
], function($, ko, api, shared, generic, data) {
    "use strict";
    return function() {
        var self = this;

        // Variables
        self.data            = data;
        self.shared          = shared;
        self.ipsLoading      = ko.observable(false);
        self.connectionError = ko.observable(false);

        // Computed
        self.canContinue = ko.computed(function() {
            var valid = true, reasons = [], fields = [];
            if (self.data.manual() === true) {
                if (self.data.nodeID() === undefined || self.data.nodeID() === '') {
                    valid = false;
                    fields.push('nodeid');
                    reasons.push($.t('alba:wizards.addalbanode.gather.nonodeid'));
                }
                if (!self.data.ip.valid()) {
                    valid = false;
                    fields.push('ip');
                    reasons.push($.t('ovs:wizards.addmgmtcenter.gather.invalidip'));
                }
            }
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
            if (self.connectionError() === true) {
                valid = false;
                fields.push('ip');
                fields.push('username');
                fields.push('password');
                fields.push('nodeid');
                reasons.push($.t('alba:wizards.addalbanode.gather.cannotconnect'));
            }
            return { value: valid, reasons: reasons, fields: fields };
        });


        // Subscriptions
        self.data.nodeID.subscribe(function() {
            self.connectionError(false);
        });
        self.data.ip.subscribe(function() {
            self.connectionError(false);
        });
        self.data.port.subscribe(function() {
            self.connectionError(false);
        });
        self.data.username.subscribe(function() {
            self.connectionError(false);
        });
        self.data.password.subscribe(function() {
            self.connectionError(false);
        });

        // Functions
        self.loadIps = function() {
            self.ipsLoading(true);
            api.get('alba/nodes', {
                queryparams: {
                    contents: 'ips',
                    discover: true,
                    ip: self.data.ip(),
                    port: self.data.port(),
                    username: self.data.username(),
                    password: self.data.password(),
                    node_id: self.data.nodeID()
                }
            })
                .done(function(data) {
                    self.data.availableIps(data.data[0].ips);
                })
                .fail(function() {
                    self.connectionError(true);
                })
                .always(function() {
                    self.ipsLoading(false);
                });
        };
        self.finish = function() {
            return $.Deferred(function(deferred) {
                generic.alertInfo(
                    $.t('alba:wizards.addalbanode.gather.started'),
                    $.t('alba:wizards.addalbanode.gather.inprogress')
                );
                deferred.resolve();
                api.post('alba/nodes', {
                    data: {
                        node_id: self.data.nodeID(),
                        ip: self.data.ip(),
                        port: self.data.port(),
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
