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
], function($, ko, generic, formBuilder, Build, Confirm, Gather, Data) {
    "use strict";
    return function(options) {
        var self = this;

        // Inherit
        Build.call(self);

        // Setup
        self.title(generic.tryGet(options, 'title', $.t('alba:wizards.add_osd.title')));
        self.modal(generic.tryGet(options, 'modal', false));

        var countDisplay = ['gather'];
        if (options.node.type() === 'ASD') {
            countDisplay = ['confirm']
        }
        var osdTypeItems;
        if (options.node.type() === 'S3') {
            osdTypeItems = ['S3']
        } else {
            osdTypeItems = ['ASD', 'AD']
        }
        var formMapping = {
            'ips': {
                'extender': {regex: generic.ipRegex},
                'displayOn': ['gather']
            },
            'port': {
                'extender': {numeric: {min: 1, max: 65535}},
                'group': 1,
                'displayOn': ['gather']
            },
            'osd_type': {
                'fieldMap': 'type',  // Translate osd_type to type so in the form it will be self.data.formdata().type
                'inputType': 'dropdown',  // Generate dropdown, needs items
                'inputItems': ko.observableArray(osdTypeItems),
                'group': 0,
                'displayOn': ['gather']
            },
            'count': {
                'extender': {numeric: {min: 1, max: 24}},
                'group': 2,
                'displayOn': countDisplay
            },
            'buckets': {
                'displayOn': ['gather'],
                'group': 3
            }
        };
        var metadata = ko.toJS(options.node.node_metadata);  // Node metadata is given by the node cluster when working with a cluster
        var formData = formBuilder.generateFormData(metadata, formMapping);
        var formQuestions = formData.questions;
        var fieldMapping = formData.fieldMapping;
        var data = new Data(options.node, options.nodeCluster, options.slots, false, formQuestions(), fieldMapping, metadata, formMapping);
        var stepOptions = {
            parent: self,
            data: data
        };
        if (options.node.type() === 'ASD') {
            data.confirmOnly(true);
            self.steps([new Confirm(stepOptions)]);
        } else {
            self.steps([new Gather(stepOptions), new Confirm(stepOptions)]);
        }
        self.activateStep();
    };
});
