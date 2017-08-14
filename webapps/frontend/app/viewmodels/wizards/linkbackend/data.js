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
define(['knockout'], function(ko){
    "use strict";
    var singleton,
        hostRegex = /^((((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?))|((([a-z0-9]+[\.\-])*[a-z0-9]+\.)+[a-z]{2,4}))$/;
    singleton = function() {
        var wizardData = {
            albaBackend:  ko.observable(),
            albaBackends: ko.observableArray([]),
            albaPreset:   ko.observable(),
            clientId:     ko.observable('').extend({removeWhiteSpaces: null}),
            clientSecret: ko.observable('').extend({removeWhiteSpaces: null}),
            domain:       ko.observable(),
            domains:      ko.observableArray([]),
            host:         ko.observable('').extend({regex: hostRegex}),
            localHost:    ko.observable(true),
            port:         ko.observable(80).extend({numeric: {min: 1, max: 65535}}),
            target:       ko.observable()
        }, resetAlbaBackends = function() {
            wizardData.albaBackends([]);
            wizardData.albaBackend(undefined);
            wizardData.albaPreset(undefined);
        };

        wizardData.clientId.subscribe(resetAlbaBackends);
        wizardData.clientSecret.subscribe(resetAlbaBackends);
        wizardData.host.subscribe(resetAlbaBackends);
        wizardData.port.subscribe(resetAlbaBackends);
        wizardData.localHost.subscribe(resetAlbaBackends);
        wizardData.enhancedPresets = ko.computed(function(){
            if (wizardData.albaBackend() === undefined){
                wizardData.albaPreset(undefined);
                return []
            }
            if (!wizardData.albaBackend().enhancedPresets().contains(wizardData.albaPreset())){
                wizardData.albaPreset(wizardData.albaBackend().enhancedPresets()[0]);
            }
            return wizardData.albaBackend().enhancedPresets();
        });
        return wizardData;
    };
    return singleton();
});
