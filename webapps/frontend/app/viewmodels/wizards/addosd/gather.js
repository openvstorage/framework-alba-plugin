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
        self.initialized      = false;

        // Computed
        // Might not be computed at this point since the bindings are applied in the activate
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

        // Durandal
        self.activate = function() {
            if (self.initialized === false) {
                self.data.formData.removeAll();  // Clear array, singleton data will still be filled
                // FormMapping data, can contain input type + item if type=dropdown, extenders for validation and fieldMappings (translations) and group
                var formMapping = {
                    'ip': {
                        'extender': {regex: generic.ipRegex},
                        'inputType': 'text',  // default if missing
                        'inputItems': null,  // default if missing
                        'group': 0
                    },
                    'port': {
                        'extender': {numeric: {min: 1, max: 65536}},
                        'group': 0
                    },
                    'osd_type': {
                        'fieldMap': 'type',  // Translate osd_type to type so in the form it will be be self.data.formdata().type
                        'inputType': 'dropdown',  // Generate dropdown, needs items
                        'inputItems': self.data.osdTypes,  // Items is of type observable
                        'group': 1
                    },
                    'count': {
                        'inputType': 'text',
                        'group': 0,
                        'extender': {numeric: {min: 1, max: 65536}}
                    }
                };
                var metadata = self.data.node().nodeMetadata().slots;
                // Determine on what basis the wizard should act
                for (var actionKey in metadata){
                    if (!metadata.hasOwnProperty(actionKey)) {
                        continue;
                    }
                    var data = metadata[actionKey];
                    if (data !== true) {
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
                        if (field in formMapping){
                            // Possibly determine target, extenders and inputType/items
                            target = formMapping[field].fieldMap || target;
                            items = formMapping[field].inputItems || items;
                            type = formMapping[field].inputType || type;
                            group = formMapping[field].group || group;
                        }
                        // Add databinding
                        var observable = ko.observable();
                        if (field in formMapping) {
                            if (formMapping[field].extender){
                                observable.extend(formMapping[field].extender)
                            }
                        }
                        var formItem = {
                            'field': field,
                            'mappedField': target,
                            'group': group,
                            'input': {
                                'type': type,  // If type = dropdown, will be populated with items
                                'items': items
                            },
                            'data': observable  // Item corresponding to this input
                        };
                        self.data.formData().push(formItem);
                    }
                }
                self.data.formData().sort(function(a, b){
                    if (a.group === b.group) {
                        return a.field.localeCompare(b.field);
                    }
                    return a.group < b.group ? -1 : 1;
                });
                // Update bindings, otherwise our dependency tree will not fill and computed will not work
                self.data.formData.valueHasMutated();
                self.initialized = true;
            }
        }
    }
});