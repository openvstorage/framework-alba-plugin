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
], function($, ko, generic, Build, Confirm, Gather, Data) {
    "use strict";
    return function(options) {
        var self = this;
        // Inherit
        Build.call(self);

        // Variables
        var data = new Data(options.albaNodeCluster);
        self.title(generic.tryGet(options, 'title', $.t('alba:wizards.register_node_under_cluster.title')));
        self.modal(generic.tryGet(options, 'modal', false));

        // Setup
        var stepOptions = {
            data: data,
            title:self.title
        };
        self.steps([new Gather(stepOptions), new Confirm(stepOptions)]);
        self.activateStep();
    };
});
