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
    'ovs/api', 'ovs/shared', 'ovs/generic', 'ovs/refresher',
    '../containers/albabackend'
], function($, ko, api, shared, generic, Refresher, AlbaBackend) {
    "use strict";
    return function() {
        var self = this;

        // Variables
        self.shared             = shared;
        self.guard              = { authenticated: true };
        self.refresher          = new Refresher();
        self.widgets            = [];
        self.loadBackendsHandle = undefined;

        // Observables
        self.loading      = ko.observable(false);
        self.albaBackends = ko.observableArray([]);

        // Functions
        self.load = function() {
            self.loading(true);
            return $.Deferred(function(deferred) {
                if (generic.xhrCompleted(self.loadBackendsHandle)) {
                    var options = {
                        sort: 'backend.name',
                        contents: '_relations,name,local_summary'
                    };
                    self.loadBackendsHandle = api.get('alba/backends', { queryparams: options })
                        .done(function(data) {
                            var guids = [], bdata = {};
                            $.each(data.data, function(index, item) {
                                guids.push(item.guid);
                                bdata[item.guid] = item;
                            });
                            generic.crossFiller(
                                guids, self.albaBackends,
                                function(guid) {
                                    return new AlbaBackend(guid);
                                }, 'guid'
                            );
                            $.each(self.albaBackends(), function(index, albaBackend) {
                                if (guids.contains(albaBackend.guid())) {
                                    albaBackend.fillData(bdata[albaBackend.guid()]);
                                }
                            });
                            self.albaBackends().sort(function(b1, b2) {
                                return b1.name() < b2.name() ? -1 : 1;
                            });
                            self.loading(false);
                            deferred.resolve();
                        })
                        .fail(function() {
                            self.loading(false);
                            deferred.reject();
                        });
                } else {
                    self.loading(false);
                    deferred.reject();
                }
            }).promise();
        };

        // Durandal
        self.activate = function() {
            self.refresher.init(function() {
                self.load()
            }, 5000);
            self.refresher.run();
            self.refresher.start();
        };
        self.deactivate = function() {
            $.each(self.widgets, function(index, item) {
                item.deactivate();
            });
            self.refresher.stop();
        };
    };
});
