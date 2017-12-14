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
    '../build', './gather', './data'
], function($, generic, Build, Gather, data) {
    "use strict";
    return function(options) {
        var self = this;
        // Inherit
        Build.call(self);

        // Variables
        self.data = data;

        // Setup
        self.title(generic.tryGet(options, 'title', $.t('alba:wizards.remove_osd.title')));
        self.modal(generic.tryGet(options, 'modal', false));
        self.data.albaOSD(options.albaOSD);
        self.data.albaNode(options.albaNode);
        self.data.completed(options.completed);
        self.data.albaBackend(options.albaBackend);
        self.steps([new Gather(self)]);
        self.activateStep();

        // Cleaning data
        data.safety({});
        data.confirmed(false);
        data.loaded(false);
    };
});
