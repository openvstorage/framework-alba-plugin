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
    'jquery', 'knockout', 'ovs/generic', '../build', './gather', './confirm', './data'],
    function($, ko, generic, build, Gather, Confirm, data) {
    "use strict";
    return function(options) {
        var self = this;
        build(self);

        // Variables
        self.data = data;

        // Setup
        self.modal(generic.tryGet(options, 'modal', false));
        self.data.backend(options.backend);
        self.data.currentPresets(options.currentPresets);
        self.steps([new Gather(), new Confirm()]);
        self.activateStep();

        // Cleaning data
        if (options.editPreset) {
            self.title(generic.tryGet(options, 'title', $.t('alba:wizards.editpreset.title')));
            self.data.currentPreset(options.currentPreset);
            self.data.name(options.currentPreset.name);
            self.data.replication(options.currentPreset.replication);
            if (self.data.currentPreset().replication === undefined) {
                self.data.advanced(true);
                self.data.accepted(true);
            } else {
                self.data.advanced(false);
                self.data.accepted(false);
            }
            self.data.compression(options.currentPreset.compression);
            self.data.encryption(options.currentPreset.encryption);
            self.data.policies([]);
            if (options.currentPreset.policies) {
                $.each(options.currentPreset.policies, function (index, policy) {
                    self.data.policies.push({
                        id: ko.observable(index),
                        k: ko.observable(policy.k).extend({numeric: {min: 0}}),
                        m: ko.observable(policy.m).extend({numeric: {min: 0}}),
                        c: ko.observable(policy.c).extend({numeric: {min: 0}}),
                        x: ko.observable(policy.x).extend({numeric: {min: 0}})
                    });
                });
            };
            self.data.editPreset(true);

        } else {
            self.title(generic.tryGet(options, 'title', $.t('alba:wizards.addpreset.title')));
            data.name('');
            data.advanced(false);
            data.accepted(false);
            data.replication(1);
            data.compression('snappy');
            data.encryption('none');
            data.policies([]);
            data.editPreset(false);
        }
    };
});
