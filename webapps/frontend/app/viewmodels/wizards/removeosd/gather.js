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
                    $.t('alba:wizards.removeosd.started'),
                    $.t('alba:wizards.removeosd.msgstarted')
                );
                api.post('alba/nodes/' + self.data.albaNode().guid() + '/reset_asd', {
                    data: {
                        asd_id: self.data.albaOSD().osdID(),
                        safety: self.data.safety()
                    }
                })
                    .then(self.shared.tasks.wait)
                    .done(function() {
                        generic.alertSuccess(
                            $.t('alba:wizards.removeosd.complete'),
                            $.t('alba:wizards.removeosd.success')
                        );
                    })
                    .fail(function(error) {
                        error = generic.extractErrorMessage(error);
                        generic.alertError(
                            $.t('ovs:generic.error'),
                            $.t('alba:wizards.removeosd.failed', { why: error })
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
                    queryparams: { asd_id: self.data.albaOSD().osdID() }
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
