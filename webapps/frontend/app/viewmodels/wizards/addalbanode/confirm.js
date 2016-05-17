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
        self.data   = data;
        self.shared = shared;

        // Computed
        self.canContinue = ko.computed(function() {
            return { value: true, reasons: [], fields: [] };
        });

        self.finish = function() {
            return $.Deferred(function(deferred) {
                generic.alertInfo(
                    $.t('alba:wizards.addalbanode.started'),
                    $.t('alba:wizards.addalbanode.inprogress')
                );
                deferred.resolve();
                api.post('alba/nodes', { data: { node_id: self.data.nodeID() } })
                    .then(self.shared.tasks.wait)
                    .done(function() {
                        generic.alertSuccess(
                            $.t('alba:wizards.addalbanode.complete'),
                            $.t('alba:wizards.addalbanode.success')
                        );
                    })
                    .fail(function(error) {
                        generic.alertError(
                            $.t('ovs:generic.error'),
                            $.t('alba:wizards.addalbanode.failed', {
                                why: error
                            })
                        );
                    });
            }).promise();
        };
    };
});
