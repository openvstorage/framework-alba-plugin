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
    'jquery', 'knockout',
    'ovs/generic', 'ovs/api',
    '../build', './confirm', './gather', './data'
], function($, ko,
            generic, api,
            Build, Confirm, Gather, Data) {
    "use strict";
    return function(options) {
        var self = this;
        // Inherit
        Build.call(self);

        // Setup
        self.title(generic.tryGet(options, 'title', $.t('alba:wizards.edit_maintenance.title')));
        self.modal(generic.tryGet(options, 'modal', false));

        // Asynchronously generate the formData
        var data = new Data(options.backend);
        var stepOptions = {
            data: data
        };

        self.steps([new Gather(stepOptions), new Confirm(stepOptions)]);
        self.activateStep();
    };
});
