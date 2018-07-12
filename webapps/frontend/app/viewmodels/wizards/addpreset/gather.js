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
                reasons.push($.t('alba:wizards.add_preset.gather.invalidname'));
            }
            if (self.data.cleanPolicies().length === 0) {
                valid = false;
                fields.push('policies');
                reasons.push($.t('alba:wizards.add_preset.gather.insufficientpolicies'));
            }
            if (currentNames.contains(self.data.name()) && !self.data.editPreset()) {
                valid = false;
                fields.push('name');
                reasons.push($.t('alba:wizards.add_preset.gather.duplicatename'));
            }
            $.each(data.policies(), function (index, policy) {
                if (policy.k() > policy.c() || policy.c() > (policy.k() + policy.m())) {
                    fields.push('c_' + policy.id());
                    if (!fields.contains('c')) {
                        valid = false;
                        fields.push('c');
                        reasons.push($.t('alba:wizards.add_preset.gather.invalidc'));
                    }
                }
                if (policy.k() === 0) {
                    fields.push('k_' + policy.id());
                    if (!fields.contains('k')) {
                        valid = false;
                        fields.push('k');
                        reasons.push($.t('alba:wizards.add_preset.gather.invalidk'));
                    }
                }
                if (policy.c() === 0) {
                    fields.push('c_' + policy.id());
                    if (!fields.contains('c')) {
                        valid = false;
                        fields.push('c');
                        reasons.push($.t('alba:wizards.add_preset.gather.invalidc'));
                    }
                }
                if (policy.x() === 0) {
                    fields.push('x_' + policy.id());
                    if (!fields.contains('x')) {
                        valid = false;
                        fields.push('x');
                        reasons.push($.t('alba:wizards.add_preset.gather.invalidx'));
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
                k: ko.observable(0).extend({numeric: { min: 0 }, rateLimit: { method: "notifyWhenChangesStop", timeout: 800 }}),
                m: ko.observable(0).extend({numeric: { min: 0 }, rateLimit: { method: "notifyWhenChangesStop", timeout: 800 }}),
                c: ko.observable(0).extend({numeric: { min: 0 }, rateLimit: { method: "notifyWhenChangesStop", timeout: 800 }}),
                x: ko.observable(0).extend({numeric: { min: 0 }, rateLimit: { method: "notifyWhenChangesStop", timeout: 800 }})
            });
        };
        self.next = function() {
            return $.Deferred(function(deferred) {
                deferred.resolve();
            }).promise();
        };
    };
});
