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
    'jquery', 'knockout', 'ovs/generic', 'ovs/formBuilder',
    '../build', './confirm', './gather', './data'
], function($, ko, generic, formBuilder, build, Confirm, Gather, data) {
    "use strict";
    return function(options) {
        var self = this;
        build(self);

        // Variables
        self.data = data;
        
        // Setup
        self.title(generic.tryGet(options, 'title', $.t('alba:wizards.add_osd.title')));
        self.modal(generic.tryGet(options, 'modal', false));
        
        var formMapping = {
            'ips': {
                'extender': {regex: generic.ipRegex},
                'inputType': 'text',  // default if missing
                'inputItems': null,  // default if missing
                'group': 0,
                'displayOn': ['gather']
            },
            'port': {
                'extender': {numeric: {min: 1, max: 65536}},
                'group': 1,
                'displayOn': ['gather']
            },
            'osd_type': {
                'fieldMap': 'type',  // Translate osd_type to type so in the form it will be self.data.formdata().type
                'inputType': 'dropdown',  // Generate dropdown, needs items
                'inputItems': ko.observableArray(['ASD', 'AD']),
                'group': 2,
                'displayOn': ['gather']
            },
            'count': {
                'inputType': 'text',
                'group': 0,
                'extender': {numeric: {min: 1, max: 24}},
                'displayOn': ['confirm']
            }
        };
        var metadata = options.node.metadata();
        var formData = formBuilder.generateFormData(metadata, formMapping);
        var formQuestions = formData.questions;
        var fieldMapping = formData.fieldMapping;

        // Cleaning data
        self.data.node(options.node);
        self.data.slots(options.slots);
        self.data.formQuestions(formQuestions());
        self.data.formFieldMapping(fieldMapping);
        self.data.formMetadata(metadata);
        self.data.formMapping(formMapping);
        self.data.completed(options.completed);

        if (self.data.node().type() === 'ASD') {
            self.data.confirmOnly(true);
            self.steps([new Confirm()]);
        } else {
            self.data.confirmOnly(false);
            self.steps([new Gather(), new Confirm()]);
        }
        self.activateStep();
    };
});
