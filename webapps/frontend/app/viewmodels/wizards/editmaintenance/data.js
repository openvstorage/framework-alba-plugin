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
define(['knockout', 'jquery', 'ovs/formBuilder'], function(ko, $, formBuilder){
    "use strict";

    function viewModel (backend, formQuestions, fieldMapping, metadata, formMapping) {
        var self = this;

        // Variables
        self.wizardName = 'edit_maintenance';

        // Observables
        self.backend = ko.observable(backend);
        self.loading = ko.observable(true);
        self.formQuestions = ko.observableArray(formQuestions || []);
        self.formFieldMapping = ko.observable(fieldMapping || {});
        self.formMapping = ko.observable(formMapping || {});
        self.formMetadata = ko.observable(metadata || {});
        self.confirmOnly = ko.observable(false);

        // Computed
        self.hasHelpText = ko.computed(function() {
            var hasText = {};
            $.each(self.formQuestions(), function(index, item) {
                var key = 'alba:wizards.' + self.wizardName + '.gather.' + item().field() + '_help';
                hasText[item().field()] = key !== $.t(key);
            });
            return hasText;
        });

        // Functions
        self.insertItem = function(field){
            // Generates an item to be added to the form
            return formBuilder.insertGeneratedFormItem(field, self.formMetadata(), self.formMapping(), self.formQuestions, self.formFieldMapping);
        };
        self.removeItem = function(index){
            return formBuilder.removeFormItem(index, self.formQuestions, self.formFieldMapping)
        };
    }
    return viewModel;
});
