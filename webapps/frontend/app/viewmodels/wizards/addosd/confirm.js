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

        self.finish = function () {
            return $.Deferred(function (deferred) {
                // Add OSD
                generic.alertInfo(
                    $.t('alba:wizards.add_osd.confirm.started'),
                    $.t('alba:wizards.add_osd.confirm.in_progress')
                );
                deferred.resolve();
                var postData = {
                    osds: [
                        {
                            slot_id: self.data.newOsd().slotId(),
                            osd_type: self.data.newOsd().type(),
                            ip: self.data.newOsd().ip(),
                            port: self.data.newOsd().port(),
                            alba_backend_guid: self.data.albaBackendGuid()
                            // todo @Check slot information for the right approach
                        }
                    ],
                    metadata: null
                };
                api.post('alba/nodes/' + self.data.newOsd().node.guid() + '/add_osds', {data: postData})
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
