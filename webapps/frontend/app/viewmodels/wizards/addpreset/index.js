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
            self.title(generic.tryGet(options, 'title', $.t('alba:wizards.edit_preset.title')));
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
            self.data.encryption(options.currentPreset.encryption[0]);
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
            self.title(generic.tryGet(options, 'title', $.t('alba:wizards.add_preset.title')));
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
