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
define(['knockout', 'jquery',
    'ovs/api', 'ovs/services/forms/form'],
    function(ko, $,
             api, Form){
    "use strict";

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

    function viewModel (backend) {
        var self = this;

        // Variables
        self.form = new Form({}, {});
        self.wizardName = 'edit_maintenance';
        self.backend = backend;

        // Observables
        self.loading = ko.observable(true);

        self.confirmOnly = ko.observable(false);

        // Asynchronously generate the formData
        $.when(api.get('alba/backends/get_maintenance_metadata'), api.get('alba/backends/' + self.backend.guid() + '/get_maintenance_config'))
            .then(function(metadata, maintenance_data) {
                var auto_cleanup_days = maintenance_data.auto_cleanup_deleted_namespaces;
                if (!(auto_cleanup_days === 0))  {
                    // Special case - 0 is false-ish so using || for easier assignment would not work
                    auto_cleanup_days = 30;
                }
                formMapping.auto_cleanup_deleted_namespaces.value = auto_cleanup_days;
                self.form.metadata = metadata;
                self.form.formMapping = formMapping;
                self.form.generateQuestions.call(self.form);
                self.loading(false)
        });
    }
    return viewModel;
});
