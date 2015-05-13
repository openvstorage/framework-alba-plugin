// Copyright 2015 CloudFounders NV
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
/*global define */
define(['knockout', 'jquery'], function(ko, $){
    "use strict";
    var nameRegex, singleton;
    nameRegex = /^[0-9a-zA-Z][a-zA-Z0-9]{1,18}[a-zA-Z0-9]$/;
    singleton = function() {
        var data = {
            backend:            ko.observable(),
            accept:             ko.observable(false),
            name:               ko.observable('').extend({ regex: nameRegex }),
            compressionOptions: ko.observableArray(['snappy', 'bz2', 'none']),
            compression:        ko.observable('snappy'),
            policies:           ko.observableArray([]),
            currentPresets:     ko.observableArray([])
        };
        data.cleanPolicies = ko.computed(function() {
            var policies = [];
            $.each(data.policies(), function(index, policy) {
                policies.push([policy.k(), policy.m(), policy.x()]);
            })
            return policies;
        });
        return data;
    };
    return singleton();
});
