// Copyright 2015 iNuron NV
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
    './data',
    'ovs/api', 'ovs/generic', 'ovs/shared'
], function($, ko, data, api, generic, shared) {
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

        // Functions
        self.finish = function() {
            return $.Deferred(function(deferred) {
                if (self.data.editPreset()) {
                    generic.alertInfo(
                        $.t('alba:wizards.editpreset.confirm.started'),
                        $.t('alba:wizards.editpreset.confirm.inprogress')
                    );
                } else {
                    generic.alertInfo(
                        $.t('alba:wizards.addpreset.confirm.started'),
                        $.t('alba:wizards.addpreset.confirm.inprogress')
                    );
                }
                deferred.resolve();
                var url = 'alba/backends/' + self.data.backend().guid();
                var postData;
                if (self.data.editPreset()) {
                    url += '/update_preset';
                    postData = {
                        name: self.data.name(),
                        policies: self.data.cleanPolicies()
                    }
                } else {
                    url += '/add_preset';
                    postData = {
                        name: self.data.name(),
                        compression: self.data.compression(),
                        policies: self.data.cleanPolicies(),
                        encryption: self.data.encryption()
                    }
                }
                api.post(url, {
                    data: postData
                })
                    .then(self.shared.tasks.wait)
                    .done(function() {
                        if (self.data.editPreset()) {
                            generic.alertSuccess(
                                $.t('alba:wizards.editpreset.confirm.complete'),
                                $.t('alba:wizards.editpreset.confirm.success')
                            );
                        } else {
                            generic.alertSuccess(
                                $.t('alba:wizards.addpreset.confirm.complete'),
                                $.t('alba:wizards.addpreset.confirm.success')
                            );
                        }
                    })
                    .fail(function(error) {
                        if (self.data.editPreset()) {
                            generic.alertError(
                                $.t('ovs:generic.error'),
                                $.t('alba:wizards.editpreset.confirm.failed', {
                                    why: error
                                })
                            );
                        } else {
                            generic.alertError(
                                $.t('ovs:generic.error'),
                                $.t('alba:wizards.addpreset.confirm.failed', {
                                    why: error
                                })
                            );
                        }
                    });
            }).promise();
        };
    };
});
