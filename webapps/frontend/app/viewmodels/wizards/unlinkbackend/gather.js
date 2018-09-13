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
    'ovs/api', 'ovs/shared', 'ovs/generic', 'ovs/refresher',
    './data'
], function($, ko, api, shared, generic, Refresher, data) {
    "use strict";
    return function(parent) {
        var self = this;

        // Variables
        self.data      = data;
        self.refresher = new Refresher();
        self.shared    = shared;

        // Handles
        self.calculateSafetyHandle = undefined;

        // Computed
        self.canContinue = ko.computed(function() {
            var valid = (!self.data.shouldConfirm() || self.data.confirmed()) && self.data.loaded() && !self.data.failedToLoad();
            return { value: valid, reasons: [], fields: [] };
        });

        // Functions
        self.finish = function() {
            return $.Deferred(function(deferred) {
                generic.alertInfo(
                    $.t('alba:wizards.unlink_backend.started'),
                    $.t('alba:wizards.unlink_backend.started_msg', {
                        global_backend: self.data.target().name(),
                        backend_to_unlink: self.data.linkedOSDInfo().name
                    })
                );
                deferred.resolve();
                api.post('alba/backends/' + self.data.target().guid() + '/unlink_alba_backends', {data: {linked_guid: self.data.linkedOSDInfo().alba_backend_guid}})
                    .then(self.shared.tasks.wait)
                    .done(function() {
                        generic.alertSuccess(
                            $.t('alba:wizards.unlink_backend.success'),
                            $.t('alba:wizards.unlink_backend.success_msg', {
                                global_backend: self.data.target().name(),
                                backend_to_unlink: self.data.linkedOSDInfo().name
                            })
                        );
                    })
                    .fail(function(error) {
                        error = generic.extractErrorMessage(error);
                        generic.alertError(
                            $.t('ovs:generic.error'),
                            $.t('alba:wizards.unlink_backend.error_msg', {error: error})
                        );
                    })
            }).promise();
        };

        // Durandal
        self.activate = function() {
            self.refresher.init(function() {
                if (generic.xhrCompleted(self.calculateSafetyHandle)) {
                    self.calculateSafetyHandle = api.get('alba/backends/' + self.data.target().guid() + '/calculate_safety', {
                        queryparams: { osd_id: self.data.linkedOSDInfo().osd_id }
                    })
                        .then(self.shared.tasks.wait)
                        .done(function(safety) {
                            self.data.safety(safety);
                        })
                        .fail(function() {
                            self.data.failedToLoad(true);
                        })
                        .always(function() {
                            self.data.loaded(true);
                        });
                }
            }, 5000);
            self.refresher.run();
            self.refresher.start();
            parent.closing.always(function() {
                self.refresher.stop();
            });
        };
    };
});
