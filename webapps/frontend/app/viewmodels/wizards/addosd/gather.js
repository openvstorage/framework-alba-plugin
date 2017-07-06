// Copyright (C) 2017 iNuron NV
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
        self.data             = data;
        self.shared           = shared;

        // Computed
        self.canContinue = ko.computed(function() {
            var reasons = [], fields = [];
            if (self.data.newOsd() === undefined){
                return {value: false, reasons: reasons, fields: fields}
            }
            else {
                if (self.data.newOsd().ip() === undefined || ! self.data.newOsd().ip.valid()) {
                    fields.push('ip');
                    reasons.push($.t('alba:wizards.add_osd.gather.invalid_ip'));
                }
                if (self.data.newOsd().port() === undefined) {
                    fields.push('port');
                    reasons.push($.t('alba:wizards.add_osd.gather.invalid_port'))
                }
                return {value: reasons.length === 0, reasons: reasons, fields: fields};
            }
        });
    }
});