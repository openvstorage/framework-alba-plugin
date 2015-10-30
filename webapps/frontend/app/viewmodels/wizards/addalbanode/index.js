// Copyright 2014 iNuron NV
//
// Licensed under the Open vStorage Non-Commercial License, Version 1.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.openvstorage.org/OVS_NON_COMMERCIAL
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
/*global define */
define([
    'jquery', 'ovs/generic',
    '../build', './gather', './data'
], function($, generic, build, Gather, data) {
    "use strict";
    return function(options) {
        var self = this;
        build(self);

        // Variables
        self.data = data;

        // Setup
        self.title(generic.tryGet(options, 'title', $.t('alba:wizards.addalbanode.title')));
        self.modal(generic.tryGet(options, 'modal', false));
        self.steps([new Gather()]);
        self.activateStep();

        // Cleaning data
        if (options.node !== undefined) {
            data.manual(false);
            data.nodeID(options.node.nodeID());
            data.ip(options.node.ip());
            data.port(options.node.port());
            data.availableIps(options.node.ips());
        } else {
            data.manual(true);
            data.nodeID('');
            data.ip('');
            data.port(8500);
            data.availableIps([]);
        }
        data.username('');
        data.password('');
        data.ips([]);
    };
});
