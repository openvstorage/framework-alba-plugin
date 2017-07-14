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
    'jquery', 'knockout',
    'ovs/generic',
    '../containers/albaosd'
], function($, ko,
            generic,
            Osd) {
    "use strict";
    return function(id) {
        var self = this;

        // Externally added
        self.node            = ko.observable();

        // Observables
        self.loaded          = ko.observable(false);
        self.osds            = ko.observableArray([]);
        self.slotId          = ko.observable(id);
        self.status          = ko.observable();  // Can be empty, ok, warning ,error
        self.statusDetail    = ko.observable();

        // Computed
        self.canFill = ko.computed(function() {
            if (self.node() === null || self.node() === undefined){
                return false
            }
           return self.node().nodeMetadata().slots.fill
        });
        self.canFillAdd = ko.computed(function(){
            if (self.node() === null || self.node() === undefined) {
                return false
            }
            return self.node().nodeMetadata().slots.fill_add
        });
        // Functions
        self.fillData = function(data) {
            self.status(data.status);
            self.statusDetail(data.status_detail || '');
            // Add osds
            var osdIds = Object.keys(data.osds || {});
            generic.crossFiller(
                osdIds, self.osds,
                function(osdId) {
                    return new Osd(osdId);
                }, 'osdID'
            );
            $.each(self.osds(), function (index, osd) {
                var osdData = data.osds[osd.osdID()];
                osd.slot = self;
                osd.fillData(osdData)
            });
            self.loaded(true);
        };

    };
});
