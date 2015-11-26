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
    './data'
], function($, ko, data) {
    "use strict";
    return function() {
        var self = this;

        // Variables
        self.data = data;

        // Computed
        self.canContinue = ko.computed(function() {
            var valid = true, reasons = [], fields = [],
                currentNames = self.data.currentPresets().map(function(item) { return item.name; });
            if (!self.data.name.valid() && !self.data.editPreset()) {
                valid = false;
                fields.push('name');
                reasons.push($.t('alba:wizards.addpreset.gather.invalidname'));
            }
            if (self.data.cleanPolicies().length === 0) {
                valid = false;
                fields.push('policies');
                reasons.push($.t('alba:wizards.addpreset.gather.insufficientpolicies'));
            }
            if (currentNames.contains(self.data.name()) && !self.data.editPreset()) {
                valid = false;
                fields.push('name');
                reasons.push($.t('alba:wizards.addpreset.gather.duplicatename'));
            }
            $.each(data.policies(), function (index, policy) {
                if (policy.k() > policy.c() || policy.c() > (policy.k() + policy.m())) {
                    fields.push('c_' + policy.id());
                    if (!fields.contains('c')) {
                        valid = false;
                        fields.push('c');
                        reasons.push($.t('alba:wizards.addpreset.gather.invalidc'));
                    }
                }
                if (policy.k() === 0) {
                    fields.push('k_' + policy.id());
                    if (!fields.contains('k')) {
                        valid = false;
                        fields.push('k');
                        reasons.push($.t('alba:wizards.addpreset.gather.invalidk'));
                    }
                }
                if (policy.c() === 0) {
                    fields.push('c_' + policy.id());
                    if (!fields.contains('c')) {
                        valid = false;
                        fields.push('c');
                        reasons.push($.t('alba:wizards.addpreset.gather.invalidc'));
                    }
                }
                if (policy.x() === 0) {
                    fields.push('x_' + policy.id());
                    if (!fields.contains('x')) {
                        valid = false;
                        fields.push('x');
                        reasons.push($.t('alba:wizards.addpreset.gather.invalidx'));
                    }
                }
            });
            return { value: valid, reasons: reasons, fields: fields };
        });

        // Functions
        self.upPolicy = function(id) {
            var policy = self.data.policies().filter(function(item) { return item.id() === id; })[0],
                index = self.data.policies.indexOf(policy);
            if (index < 1) {
                return;
            }
            self.data.policies()[index] = self.data.policies().splice(index - 1, 1, self.data.policies()[index])[0];
            self.data.policies.valueHasMutated();
        };
        self.downPolicy = function(id) {
            var policy = self.data.policies().filter(function(item) { return item.id() === id; })[0],
                index = self.data.policies.indexOf(policy);
            if (index >= self.data.policies().length - 1) {
                return;
            }
            self.data.policies()[index] = self.data.policies().splice(index + 1, 1, self.data.policies()[index])[0];
            self.data.policies.valueHasMutated();
        };
        self.removePolicy = function(id) {
            self.data.policies(self.data.policies().filter(function(item) { return item.id() !== id; }));
        };
        self.addPolicy = function() {
            var newID = Math.max(0, Math.max.apply(this, self.data.policies().map(function(item) { return item.id(); }))) + 1;
            self.data.policies.push({
                id: ko.observable(newID),
                k: ko.observable(0).extend({numeric: { min: 0 }}),
                m: ko.observable(0).extend({numeric: { min: 0 }}),
                c: ko.observable(0).extend({numeric: { min: 0 }}),
                x: ko.observable(0).extend({numeric: { min: 0 }})
            });
        };
        self.next = function() {
            return $.Deferred(function(deferred) {
                deferred.resolve();
            }).promise();
        };
    };
});
