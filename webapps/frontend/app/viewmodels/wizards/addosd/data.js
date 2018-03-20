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

    function Data(node, nodeCluster, slots, confirmOnly, formQuestions, fieldMapping, formMetadata, formMapping) {
        var self = this;
        self.node               = ko.observable(node);
        self.nodeCluster        = ko.observable(nodeCluster);
        self.slots              = ko.observable(slots);
        self.formQuestions      = ko.observable(formQuestions);
        self.formFieldMapping   = ko.observable(fieldMapping);
        self.formMetadata       = ko.observable(formMetadata);
        self.formMapping        = ko.observable(formMapping);
        self.confirmOnly        = ko.observable(confirmOnly);

        self.hasHelpText = ko.pureComputed(function() {
            var hasText = {};
            $.each(self.formQuestions(), function(index, item) {
                var key = 'alba:wizards.add_osd.gather.' + item().field() + '_help';
                hasText[item().field()] = key !== $.t(key);
            });
            return hasText;
        });
        self.workingWithCluster = ko.pureComputed(function() {
            return !!self.nodeCluster()
        })
    }
    Data.prototype = {
        insertItem: function(field) {
            return formBuilder.insertGeneratedFormItem(field, this.formMetadata(), this.formMapping(), this.formQuestions, this.formFieldMapping);
        },
        removeItem: function(index) {
            return formBuilder.removeFormItem(index, this.formQuestions, this.formFieldMapping)
        }
    };
    return Data;
});
