// Copyright 2015 iNuron NV
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
define(['durandal/app', 'knockout', 'jquery'], function(app, ko, $){
    "use strict";
    var nameRegex, singleton;
    nameRegex = /^[0-9a-zA-Z][a-zA-Z0-9]{1,18}[a-zA-Z0-9]$/;
    singleton = function() {
        var data = {
            backend:            ko.observable(),
            advanced:           ko.observable(false),
            accepted:           ko.observable(false),
            replication:        ko.observable(1).extend({ numeric: { min: 1, max: 5 }}),
            name:               ko.observable('').extend({ regex: nameRegex }),
            compressionOptions: ko.observableArray(['snappy', 'bz2', 'none']),
            compression:        ko.observable('snappy'),
            encryptionOptions:  ko.observableArray(['aes-cbc-256', 'none']),
            encryption:         ko.observable('none'),
            policies:           ko.observableArray([]),
            currentPresets:     ko.observableArray([]),
            currentPreset:      ko.observable(),
            editPreset:         ko.observable(false),
            canEdit:            ko.observable(true)
        };

        data.canEdit = ko.computed(function() {
            return !data.editPreset()
        });

        data.cleanPolicies = ko.computed(function() {
            var policies = [], i = 0, replication = data.replication() - 1;
            if (data.advanced()) {
                $.each(data.policies(), function (index, policy) {
                    policies.push([policy.k(), policy.m(), policy.c(), policy.x()]);
                });
            } else {
                policies.push([1, replication, 1, 1 + replication]);
            }
            return policies;
        });
        return data;
    };
    return singleton();
});
