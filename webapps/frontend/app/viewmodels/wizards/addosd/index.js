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
    'jquery', 'knockout', 'ovs/generic',
    '../build', './confirm', './gather', './data'
], function($, ko, generic, build, Confirm, Gather, data) {
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
            'ip': {
                'extender': {regex: generic.ipRegex},
                'inputType': 'text',  // default if missing
                'inputItems': null,  // default if missing
                'group': 0,
                'displayOn': ['gather']
            },
            'port': {
                'extender': {numeric: {min: 1, max: 65536}},
                'group': 0,
                'displayOn': ['gather']
            },
            'osd_type': {
                'fieldMap': 'type',  // Translate osd_type to type so in the form it will be self.data.formdata().type
                'inputType': 'dropdown',  // Generate dropdown, needs items
                'inputItems': ko.observableArray(['ASD', 'AD']),
                'group': 1,
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
        var formDatas = [];
        // Determine on what basis the wizard should act
        for (var actionKey in metadata){
            if (!metadata.hasOwnProperty(actionKey)) {
                continue;
            }
            if (metadata[actionKey] !== true) {
                continue
            }
            // Question data is stored within the key_metadata part
            var metadataKey = actionKey + '_metadata';
            for (var field in metadata[metadataKey]){
                if (!metadata[metadataKey].hasOwnProperty(field)) {
                    continue;
                }
                // @TODO use the type returned by the api to determine the type here
                // current types returned: ip, port, osd_type, integer
                var target = field;
                var items = null;
                var type = 'text';
                var group = 0;
                var display = undefined;
                if (field in formMapping){
                    // Possibly determine target, extenders and inputType/items
                    target = formMapping[field].fieldMap || target;
                    items = formMapping[field].inputItems || items;
                    type = formMapping[field].inputType || type;
                    group = formMapping[field].group || group;
                    display = formMapping[field].displayOn;
                }
                // Add data-binding
                var observable = ko.observable();
                if (field in formMapping) {
                    if (formMapping[field].extender){
                        observable = observable.extend(formMapping[field].extender)
                    }
                }
                var formItem = {
                    'data': observable,  // Item corresponding to this input
                    'field': field,
                    'group': group,
                    'display': display,
                    'mappedField': target,
                    'input': {
                        'type': type,  // If type = dropdown, will be populated with items
                        'items': items
                    }
                };
                formDatas.push(formItem);
            }
        }
        formDatas.sort(function(a, b){
            if (a.group === b.group) {
                return a.field.localeCompare(b.field);
            }
            return a.group < b.group ? -1 : 1;
        });

        // Cleaning data
        self.data.node(options.node);
        self.data.slots(options.slots);
        self.data.formData(formDatas);
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
