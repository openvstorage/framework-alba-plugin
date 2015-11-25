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
define(['knockout'], function(ko){
    "use strict";
    var ipRegex, singleton;
    ipRegex = /^(((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?))$/;
    singleton = function() {
        return {
            manual:       ko.observable(false),
            nodeID:       ko.observable(),
            ip:           ko.observable().extend({ regex: ipRegex }),
            port:         ko.observable(8500).extend({ numeric: { min: 1, max: 65536 } }),
            username:     ko.observable(),
            password:     ko.observable(),
            availableIps: ko.observableArray([]),
            ips:          ko.observableArray([])
        };
    };
    return singleton();
});
