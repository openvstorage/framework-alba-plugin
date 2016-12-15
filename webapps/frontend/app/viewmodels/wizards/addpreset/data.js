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
define(['durandal/app', 'knockout', 'jquery'], function(app, ko, $){
    "use strict";
    var nameRegex, singleton;
    nameRegex = /^[0-9a-zA-Z][a-zA-Z0-9-_]{1,18}[a-zA-Z0-9]$/;
    singleton = function() {
        var data = {
            backend:            ko.observable(),
            advanced:           ko.observable(false),
            accepted:           ko.observable(false),
            replication:        ko.observable(1).extend({ numeric: { min: 1, max: 5 }}),
            name:               ko.observable('').extend({ regex: nameRegex }),
            compressionOptions: ko.observableArray(['snappy', 'bz2', 'none']),
            compression:        ko.observable('snappy'),
            encryptionOptions:  ko.observableArray(['aes-ctr-256', 'aes-cbc-256', 'none']),
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
