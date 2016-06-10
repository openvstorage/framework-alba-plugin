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
        self.abGuidDomainMap   = {};
        self.domainGuidNameMap = {};
        self.guard             = { authenticated: true };
        self.refresher         = new Refresher();
        self.shared            = shared;
        self.widgets           = [];

        // Handles
        self.loadAlbaBackendsHandle = undefined;
        self.loadBackendsHandle     = undefined;
        self.loadDomainsHandle      = undefined;

        // Observables
        self.albaBackends     = ko.observableArray([]);
        self.domainBackendMap = ko.observable({'LOCAL': ko.observableArray([]),
                                               'GLOBAL': ko.observableArray([])});
        self.loading          = ko.observable(false);
        self.selectedGroup    = ko.observable({'name': 'GLOBAL', 'disabled': false, 'translate': true});

        // Computed
        self.availableGroups = ko.computed(function() {
            var customgroups  = [],
                defaultgroups = [{'name': 'GLOBAL', 'disabled': false, 'translate': true},
                                 {'name': 'LOCAL',  'disabled': false, 'translate': true}];
            $.each(self.domainBackendMap(), function(key, _) {
                var item = {'name': key, 'disabled': false, 'translate': false};
                if (key === 'GLOBAL' || key === 'LOCAL') {
                    return true;
                }
                if (!generic.arrayHasElementWithProperty(customgroups, 'name', key)) {
                    customgroups.push(item);
                }
                customgroups.sort(function(group1, group2) {
                    return group1.name < group2.name ? -1 : 1;
                });
            });
            if (customgroups.length > 0) {
                defaultgroups.push({'name': '-----------------', 'disabled': true,  'translate': false});
            }
            $.each(customgroups, function(_, item) {
                defaultgroups.push(item);
            });
            return defaultgroups;
        });
        self.groupedAlbaBackends = ko.computed(function() {
            if (self.domainBackendMap().hasOwnProperty(self.selectedGroup().name)) {
                var groupedBackends = self.domainBackendMap()[self.selectedGroup().name]();
                groupedBackends.sort(function(backend1, backend2) {
                    return backend1.name() < backend2.name() ? -1: 1;
                });
                return groupedBackends;
            }
            return [];
        });

        // Functions
        self.load = function() {
            self.loading(true);
            return $.Deferred(function(deferred) {
                var calls = [];
                calls.push(self.loadAlbaBackends());
                calls.push(self.loadBackends());
                calls.push(self.loadDomains());
                $.when.apply($, calls)
                    .done(function() {
                        $.each(self.albaBackends(), function(_, albaBackend) {
                            var map = self.domainBackendMap();
                            if (!map[albaBackend.scaling()]().contains(albaBackend)) {
                                map[albaBackend.scaling()]().push(albaBackend);
                            }
                            if (self.abGuidDomainMap.hasOwnProperty(albaBackend.guid())) {
                                $.each(self.abGuidDomainMap[albaBackend.guid()], function(_, domainGuid) {
                                    if (self.domainGuidNameMap.hasOwnProperty(domainGuid)) {
                                        var domainName = self.domainGuidNameMap[domainGuid];
                                        if (!map.hasOwnProperty(domainName)) {
                                            map[domainName] = ko.observableArray([]);
                                        }
                                        if (!map[domainName]().contains(albaBackend)) {
                                            map[domainName]().push(albaBackend);
                                        }
                                    }
                                });
                            }
                            self.domainBackendMap(map);
                        });
                    })
                    .always(function() {
                        self.loading(false);
                        deferred.resolve();
                    });
            }).promise();
        };
        self.loadAlbaBackends = function() {
            return $.Deferred(function(deferred) {
                if (generic.xhrCompleted(self.loadAlbaBackendsHandle)) {
                    var options = {
                        sort: 'backend.name',
                        contents: '_relations,name,local_summary'
                    };
                    self.loadAlbaBackendsHandle = api.get('alba/backends', { queryparams: options })
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
                            deferred.resolve();
                        })
                        .fail(function() {
                            deferred.reject();
                        });
                } else {
                    deferred.reject();
                }
            }).promise();
        };
        self.loadBackends = function() {
            return $.Deferred(function(deferred) {
                if (generic.xhrCompleted(self.loadBackendsHandle)) {
                    var options = {
                        contents: 'linked_guid,regular_domains'
                    };
                    self.loadBackendsHandle = api.get('backends', { queryparams: options })
                        .done(function(data) {
                            $.each(data.data, function(index, item) {
                                self.abGuidDomainMap[item.linked_guid] = item.regular_domains;
                            });
                            deferred.resolve();
                        })
                        .fail(function() {
                            deferred.reject();
                        });
                } else {
                    deferred.reject();
                }
            }).promise();
        };
        self.loadDomains = function() {
            return $.Deferred(function(deferred) {
                if (generic.xhrCompleted(self.loadDomainsHandle)) {
                    self.loadDomainsHandle = api.get('domains', { queryparams: { contents: '' }})
                        .done(function(data) {
                            $.each(data.data, function(index, item) {
                                self.domainGuidNameMap[item.guid] = item.name;
                            });
                            deferred.resolve();
                        })
                        .fail(deferred.reject);
                } else {
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
