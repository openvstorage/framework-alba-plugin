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
                        error = generic.extractErrorMessage(error);
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
