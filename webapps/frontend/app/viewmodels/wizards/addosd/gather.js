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
    'jquery', 'knockout', 'ovs/shared', './data'
], function($, ko, shared, data) {
    "use strict";
    return function() {
        var self = this;

        // Variables
        self.data   = data;
        self.shared = shared;

        // Computed
        self.canContinue = ko.computed(function() {
            var reasons = [], fields = [];
            $.each(self.data.formData(), function(index, formItem){
                var observable = formItem.data;
                if (observable() === undefined || (typeof observable.valid === 'function' && !observable.valid())){
                    fields.push(formItem.field);
                    reasons.push($.t('alba:wizards.add_osd.gather.invalid_' + formItem.field))
                }
            });
            return {value: reasons.length === 0, reasons: reasons, fields: fields};
        });
    }
});
