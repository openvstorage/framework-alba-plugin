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
    '../build', './confirm', './data'
], function($, generic, build, Confirm, data) {
    "use strict";
    return function(options) {
        var self = this;
        build(self);

        // Variables
        self.data = data;

        // Setup
        self.title(generic.tryGet(options, 'title', (options.oldNode === undefined ? $.t('alba:wizards.add_alba_node.title') : $.t('alba:wizards.replace_alba_node.title'))));
        self.modal(generic.tryGet(options, 'modal', false));
        self.steps([new Confirm()]);
        self.activateStep();

        // Cleaning data
        data.newNode(options.newNode);
        data.oldNode(options.oldNode);
    };
});
