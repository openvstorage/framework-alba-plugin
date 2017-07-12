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

        // Observables
        self.questions = ko.observableArray([]);

        // Computed
        // Might not be computed at this point since the bindings are applied in the activate
        self.canContinue = ko.computed(function() {
            var reasons = [], fields = [];
            $.each(self.questions(), function(index, question){
                var item = self.data[question.input.target];
                if (item() === undefined || (typeof item.valid === 'function' && !item.valid())){
                    fields.push(question.id);
                    reasons.push($.t('alba:wizards.add_osd.gather.invalid_' + question.id))
                }
            });
            return {value: reasons.length === 0, reasons: reasons, fields: fields};
        });

        // Durandal
        self.activate = function() {
            if (self.initialized === false) {
                var mappedFields = {'osd_type': 'type'};  // Map fields of metadata to fields of our view
                var mappedExtenders = {
                    'ip': {regex: generic.ipRegex},
                    'port': {numeric: {min: 1, max: 65536}}
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
                        var question = {};
                        question.id = field;
                        var target = mappedFields[field] || field;
                        var items = field === 'osd_type' ? self.data.osdTypes : null;
                        var type = field === 'osd_type' ? 'dropdown' : 'text'  // If type = dropdown, will be populated with items
                        question.input = {
                            'type': type,  // If type = dropdown, will be populated with items
                            'items': items,
                            'target': target
                        };
                        // Might do something more generic in the future for grouping
                        question.group = ['ip', 'port'].contains(field) ? 0 : 1;
                        self.questions().push(question);
                        // Push observables to data
                        self.data[target] = ko.observable();
                        if (target in mappedExtenders) {
                            self.data[target].extend(mappedExtenders[target])
                        }
                    }
                }
                self.questions().sort(function(a, b){
                    if (a.group === b.group) {
                        return a.id.localeCompare(b.id);
                    }
                    return a.group < b.group ? -1 : 1;
                });
                self.initialized = true;
            }
        }
    }
});