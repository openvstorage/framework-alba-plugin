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
    'jquery', 'ovs/generic',
    '../build', './confirm', './gather', './data'
], function($, generic, build, Confirm, Gather, data) {
    "use strict";
    return function(options) {
        var self = this;
        build(self);

        // Variables
        self.data = data;

        // Setup
        self.title(generic.tryGet(options, 'title', $.t('alba:wizards.add_osd.title')));
        self.modal(generic.tryGet(options, 'modal', false));

        // Cleaning data
        self.data.node(options.node);
        self.data.slot(options.slot);
        self.data.completed(options.completed);
        self.data.albaBackend(options.albaBackend);
        self.data.confirmOnly(options.confirmOnly);

        if (options.confirmOnly) {
            self.steps([new Confirm()]);
        } else {
            self.steps([new Gather(), new Confirm()]);
        }
        self.activateStep();
    };
});
