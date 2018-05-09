// Copyright (C) 2018 iNuron NV
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
    'jquery', 'knockout', 'ovs/shared', 'ovs/formBuilder'
], function($, ko, shared, formBuilder) {
    "use strict";
    return function(stepOptions) {
        var self = this;

        // Variables
        self.data   = stepOptions.data;
        self.shared = shared;

        // Computed
        self.canContinue = ko.computed(function() {
            if (self.data.loading()) {
                return {value: false, reasons: [$.t('alba:wizards.' + self.data.wizardName + '.gather.loading')], fields: []}
            }
            return formBuilder.validateForm('alba:wizards.' + self.data.wizardName + '.invalid_', self.data.formQuestions());
        });
    }
});
