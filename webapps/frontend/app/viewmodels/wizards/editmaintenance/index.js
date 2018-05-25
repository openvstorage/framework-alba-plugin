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
define([
    'jquery', 'knockout', 'ovs/generic', 'ovs/formBuilder', 'ovs/api',
    '../build', './confirm', './gather', './data'
], function($, ko, generic, formBuilder, api, Build, Confirm, Gather, Data) {
    "use strict";
    return function(options) {
        var self = this;
        // Inherit
        Build.call(self);

        // Setup
        self.title(generic.tryGet(options, 'title', $.t('alba:wizards.edit_maintenance.title')));
        self.modal(generic.tryGet(options, 'modal', false));

        // Variables
        var formMapping = {
            'auto_cleanup_deleted_namespaces': {
                'inputType': 'widget',
                'widgetName': 'numberinput',
                'group': 0,
                'extender': {numeric: {min: 0}},
                'displayOn': ['gather'],
                'value': 30
            }
        };
        // Asynchronously generate the formData
        var data = new Data(options.backend);
        $.when(api.get('alba/backends/get_maintenance_metadata'), api.get('alba/backends/' + data.backend().guid() + '/get_maintenance_config'))
            .then(function(metadata, maintenance_data) {
                var auto_cleanup_days = maintenance_data.auto_cleanup_deleted_namespaces;
                if (!(auto_cleanup_days === 0))  {
                    // Special case - 0 is false-ish so using || for easier assignment would not work
                    auto_cleanup_days = 30;
                }
                formMapping.auto_cleanup_deleted_namespaces.value = auto_cleanup_days;
                var formData = formBuilder.generateFormData(metadata, formMapping);
                var formQuestions = formData.questions;
                var fieldMapping = formData.fieldMapping;
                data.formQuestions(formQuestions());
                data.formFieldMapping(fieldMapping);
                data.formMetadata(metadata);
                data.formMapping(formMapping);
                data.loading(false)
        });
        var stepOptions = {
            data: data
        };

        self.steps([new Gather(stepOptions), new Confirm(stepOptions)]);
        self.activateStep();
    };
});
