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
    'ovs/api', 'ovs/shared', 'ovs/generic',
    './data'
], function($, ko, api, shared, generic, data) {
    "use strict";
    return function() {
        var self = this;

        // Variables
        self.data = data;
        self.shared = shared;

        // Computed
        self.canContinue = ko.computed(function () {
            return {value: true, reasons: [], fields: []};
        });
        // Function

        self.gatherPostData = function() {
            var osdData = {};
            var postData = {'osds': [osdData], metadata: null};
            // Gather info from the dynamic form
            var fields = []; // Remove this when the type is fetched by alba
            $.each(self.data.formData(), function(index, formItem){
                osdData[formItem.field] = formItem.data();
                fields.push(formItem.field)
            });

            // @TODO remove this part as type should be fetched
            if (!fields.contains('osd_type')) {
                osdData.osd_type = 'ASD';
            }
            // Append some necessary bits
            osdData.alba_backend_guid = self.data.albaBackend().guid();

            postData.slot_id = self.data.slot().slotId();
            postData.albanode_guid = self.data.node().guid();

            return postData
        };
        self.finish = function () {
            return $.Deferred(function (deferred) {
                var pData = self.gatherPostData();
                var amount = pData.osds[0].count;
                generic.alertInfo(
                    $.t('alba:wizards.add_osd.confirm.started'),
                    $.t('alba:wizards.add_osd.confirm.started_msg', {
                        name: self.data.slot().slotId(),
                        multi: amount > 1 ? 's': '',
                        amount: amount
                    })
                );
                (function(postData, node, slot, osdAmount, completed, dfd) {
                    api.post('alba/nodes/' + node.guid() + '/fill_slot', {data: postData})
                    .then(self.shared.tasks.wait)
                    .done(function () {
                        generic.alertSuccess(
                            $.t('alba:wizards.add_osd.confirm.success'),
                            $.t('alba:wizards.add_osd.confirm.success_msg', {
                                name: slot.slotId(),
                                multi: osdAmount > 1 ? 's': '',
                                amount: osdAmount
                            })
                        );
                        completed.resolve(true);
                    })
                    .fail(function (error) {
                        error = generic.extractErrorMessage(error);
                        generic.alertError(
                            $.t('alba:wizards.add_osd.confirm.failure'),
                            $.t('alba:wizards.add_osd.confirm.failure_msg', {
                                why: error,
                                name: slot.slotId(),
                                multi: osdAmount > 1 ? 's': '',
                                amount: osdAmount
                            })
                        );
                        completed.resolve(false);
                    });
                    dfd.resolve();
                })(pData, self.data.node(), self.data.slot(), amount, self.data.completed(), deferred);
            }).promise();
        };
    }
});
