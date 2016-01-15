// Copyright 2014 iNuron NV
//
// Licensed under the Open vStorage Modified Apache License (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.openvstorage.org/license
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
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
        self.title(generic.tryGet(options, 'title', $.t('alba:wizards.addalbanode.title')));
        self.modal(generic.tryGet(options, 'modal', false));
        self.steps([new Confirm()]);
        self.activateStep();

        // Cleaning data
        data.nodeID(options.node.nodeID());
        data.ip(options.node.ip());
        data.port(options.node.port());
        data.username(options.node.username());
        data.asdIPs(options.node.ips());
    };
});
