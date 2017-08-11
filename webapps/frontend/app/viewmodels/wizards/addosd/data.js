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
define(['knockout', 'jquery', 'ovs/formBuilder'], function(ko, $, formBuilder){
    "use strict";

    var singleton = function() {
        var data = {
            node: ko.observable(),
            slots: ko.observableArray([]),
            formQuestions: ko.observableArray([]),
            formFieldMapping: ko.observable(),
            formMapping: ko.observable(),
            formMetadata: ko.observable(),
            completed: ko.observable(),
            confirmOnly: ko.observable()
        };
        
        // Computed
        data.hasHelpText = ko.computed(function() {
            var hasText = {};
            $.each(data.formQuestions(), function(index, item) {
                var key = 'alba:wizards.add_osd.gather.' + item().field() + '_help';
                hasText[item().field()] = key !== $.t(key);
            });
            return hasText;
        });

        // Functions
        data.insertItem = function(field){
            // Generates an item to be added to the form
            return formBuilder.insertGeneratedFormItem(field, data.formMetadata(), data.formMapping(), data.formQuestions, data.formFieldMapping);
        };

        data.removeItem = function(index){
            return formBuilder.removeFormItem(index, data.formQuestions, data.formFieldMapping)
        };
        return data;
    };
    return singleton();
});
