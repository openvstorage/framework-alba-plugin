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
    'ovs/api', 'ovs/shared', 'ovs/generic', 'ovs/formBuilder'
], function($, ko, api, shared, generic, formBuilder) {
    "use strict";
    return function(stepOptions) {
        var self = this;

        // Variables
        self.data   = stepOptions.data;
        self.shared = shared;

        // Computed
        self.canContinue = ko.computed(function () {
            return {value: true, reasons: [], fields: []};
        });

        // Function
        self.finish = function () {
            var maintenanceConfig = formBuilder.gatherData(self.data.formFieldMapping);
            return $.when()
                .then(function() {
                    generic.alertInfo(
                            $.t('alba:wizards.' + self.data.wizardName + '.confirm.started'),
                            $.t('alba:wizards.' + self.data.wizardName + '.confirm.started_msg', {})
                    );
                    return api.post('alba/backends/' + self.data.backend().guid() + '/set_maintenance_config', {data: {maintenance_config: maintenanceConfig}})
                        .then(function() {
                            generic.alertSuccess(
                                $.t('alba:wizards.' + self.data.wizardName + '.confirm.success'),
                                $.t('alba:wizards.' + self.data.wizardName + '.confirm.success_msg', {})
                            );
                        }, function(error) {
                            error = generic.extractErrorMessage(error);
                            generic.alertError(
                                $.t('alba:wizards.add_osd.confirm.failure'),
                                $.t('alba:wizards.add_osd.confirm.failure_msg', {why: error})
                            );
                        });
                });
        };
    }
});
