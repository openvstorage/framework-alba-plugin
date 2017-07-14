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
            var data = {'osd': osdData, metadata: null};

            var apiPath = undefined;
            if (self.data.slot().canFill()) {
                apiPath = 'alba/nodes/' + self.data.node().guid() + '/fill_slot'
            }
            else if (self.data.slot().canFillAdd()) {
                apiPath = 'alba/backends/' + self.data.albaBackend().guid() + '/add_osds'
            }
            if (apiPath === undefined) {
                generic.alertError(
                    $.t('ovs:generic.error'),
                    $.t('alba:wizards.add_osd.confirm.failed', {why: 'Unable to perform action.'})
                );
            }
            var postData = {
                path: apiPath,
                data: data
            };
            // Gather info from the dynamic form
            var fields = []; // Remove this when the type is fetched by alba
            $.each(self.data.formData(), function(index, formItem){
                osdData[formItem.field] = formItem.data;
                fields.push(formItem.field)
            });

            // @TODO remove this part as type should be fetched
            if (!fields.contains('osd_type')) {
                osdData.osd_type = 'ASD';
            }
            // Append some necessary bits
            data.slot_id = self.data.slot().slotId();
            data.alba_backend_guid = self.data.albaBackend().guid();

            return postData
        };
        self.finish = function () {
            return $.Deferred(function (deferred) {
                // Add OSD
                generic.alertInfo(
                    $.t('alba:wizards.add_osd.confirm.started'),
                    $.t('alba:wizards.add_osd.confirm.in_progress')
                );
                deferred.resolve();
                var postData = self.gatherPostData();
                api.post(postData.path, {data: postData.data})
                    .then(self.shared.tasks.wait)
                    .done(function () {
                        generic.alertSuccess(
                            $.t('alba:wizards.add_osd.confirm.complete'),
                            $.t('alba:wizards.add_osd.confirm.success')
                        );
                    })
                    .fail(function (error) {
                        error = generic.extractErrorMessage(error);
                        generic.alertError(
                            $.t('ovs:generic.error'),
                            $.t('alba:wizards.add_osd.confirm.failed', {why: error})
                        );
                    });
            }).promise();
        };
    }
});
