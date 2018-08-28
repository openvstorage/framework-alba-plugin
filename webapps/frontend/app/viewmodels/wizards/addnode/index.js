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
        var data = new Data(options.newNode, options.oldNode, options.confirmOnly);
        var title = options.oldNode === undefined ? $.t('alba:wizards.add_node.title') : $.t('alba:wizards.replace_node.title');

        // Observables
        self.title = ko.pureComputed(function() {  // Overrule default title
            if (data.workingWithCluster()) { return $.t('alba:wizards.add_nodecluster.title')}
            else { return title }
        });
        self.modal(generic.tryGet(options, 'modal', false));

        // Setup
        var stepOptions = {
            data: data,
            title:self.title
        };
        if (options.confirmOnly) { self.steps([new Confirm(stepOptions)]); }
        else { self.steps([new Gather(stepOptions), new Confirm(stepOptions)]); }

        self.activateStep();
    };
});
