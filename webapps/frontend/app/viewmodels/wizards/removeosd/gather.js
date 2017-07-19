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
            return $.Deferred(function(deferred) {
                (function(albaOSD, albaNode) {
                    generic.alertInfo(
                        $.t('alba:wizards.remove_osd.started'),
                        $.t('alba:wizards.remove_osd.started_msg', {what: albaOSD.osdID()})
                    );
                    api.post('alba/nodes/' + albaNode.guid() + '/reset_osd', {
                        data: {
                            osd_id: albaOSD.osdID(),
                            safety: self.data.safety()
                        }
                    })
                        .then(self.shared.tasks.wait)
                        .done(function() {
                            generic.alertSuccess(
                                $.t('alba:wizards.remove_osd.complete'),
                                $.t('alba:wizards.remove_osd.success', {what: albaOSD.osdID()})
                            );
                        })
                        .fail(function(error) {
                            error = generic.extractErrorMessage(error);
                            generic.alertError(
                                $.t('ovs:generic.error'),
                                $.t('alba:wizards.remove_osd.failed', {what: albaOSD.osdID(), why: error})
                            );
                        })
                        .always(function() {
                            albaOSD.processing(false);
                        });
                    deferred.resolve();
                })(self.data.albaOSD(), self.data.albaNode());
            }).promise();
        };

        // Durandal
        self.activate = function() {
            self.data.albaOSD().processing(true);
            self.refresher.init(function() {
                api.get('alba/backends/' + self.data.albaBackend().guid() + '/calculate_safety', {
                    queryparams: { osd_id: self.data.albaOSD().osdID() }
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
