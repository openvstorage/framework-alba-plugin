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
    function ViewModel(albaOSD, albaNode, albaBackend) {
        var self = this;
        self.safety = ko.observable({});
        self.loaded = ko.observable(false);
        self.albaOSD =  ko.observable(albaOSD);
        self.albaNode= ko.observable(albaNode);
        self.confirmed=  ko.observable(false);
        self.albaBackend= ko.observable(albaBackend);

        self.shouldConfirm = ko.computed(function() {
            var safety = self.safety();
            return (safety.lost !== undefined && safety.lost > 0) || (safety.critical !== undefined && safety.critical > 0);
        });
    }
    return ViewModel;
});
