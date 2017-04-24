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
    'ovs/api', 'ovs/shared', 'ovs/generic',
    './data',
    '../../containers/albabackend', '../../containers/domain'
], function($, ko, api, shared, generic, data, AlbaBackend, Domain) {
    "use strict";
    return function() {
        var self = this;

        // Variables
        self.data   = data;
        self.shared = shared;

        // Observables
        self.albaPresetMap        = ko.observable({});
        self.albaBackendDomainMap = ko.observable({});
        self.loadingAlbaBackends  = ko.observable(true);
        self.loadingDomains       = ko.observable(true);
        self.invalidAlbaInfo      = ko.observable(false);

        // Handles
        self.loadAlbaBackendsHandle = undefined;
        self.loadDomainsHandle      = undefined;

        self.data.albaBackend.subscribe(function(backend) {
            if (backend !== undefined && self.albaBackendDomainMap().hasOwnProperty(backend.guid())) {
                var domainGuids = self.albaBackendDomainMap()[backend.guid()];
                $.each(self.data.domains(), function(index, domain) {
                    if (domainGuids.contains(domain.guid())) {
                        self.data.domain(domain);
                        return false;
                    }
                });
            }
        });
        self.data.localHost.subscribe(function(local) {
            if (local === true || (self.data.host() !== '' && self.data.clientId() !== '' && self.data.clientSecret() !== '' && self.data.port() !== 1)) {
                self.loadAlbaBackends();
            }
        });

        // Computed
        self.isPresetAvailable = ko.computed(function() {
            var presetAvailable = true;
            if (self.data.albaBackend() !== undefined && self.data.albaPreset() !== undefined) {
                var guid = self.data.albaBackend().guid(),
                    name = self.data.albaPreset().name;
                if (self.albaPresetMap().hasOwnProperty(guid) && self.albaPresetMap()[guid].hasOwnProperty(name)) {
                    presetAvailable = self.albaPresetMap()[guid][name];
                }
            }
            return presetAvailable;
        });
        self.selectedDomainLinkedToBackend = ko.computed(function() {
            if (!self.data.localHost()) {
                return true;
            }
            if (self.data.domain() !== undefined && self.data.albaBackend() !== undefined && self.albaBackendDomainMap().hasOwnProperty(self.data.albaBackend().guid())) {
                return self.albaBackendDomainMap()[self.data.albaBackend().guid()].contains(self.data.domain().guid());
            }
        });
        self.loadingInformation = ko.computed(function() {
            return self.loadingAlbaBackends() || self.loadingDomains();
        });
        self.canContinue = ko.computed(function() {
            var reasons = [], fields = [];
            if (self.loadingInformation() === false) {
                if (self.invalidAlbaInfo()) {
                    reasons.push($.t('alba:wizards.link_backend.invalid_alba_info'));
                    fields.push('clientid');
                    fields.push('clientsecret');
                    fields.push('host');
                } else {
                    if (self.data.albaBackend() === undefined && self.loadingAlbaBackends() === false) {
                        reasons.push($.t('alba:wizards.link_backend.choose_backend'));
                        fields.push('backend');
                    }
                    if (self.data.albaBackend() !== undefined && self.data.albaPreset() === undefined) {
                        reasons.push($.t('alba:wizards.link_backend.choose_preset'));
                        fields.push('preset');
                    }
                }
                if (!self.isPresetAvailable()) {
                    reasons.push($.t('alba:wizards.link_backend.alba_preset_unavailable'));
                    fields.push('preset');
                }
            }
            return { value: reasons.length === 0, reasons: reasons, fields: fields };
        });

        // Functions
        self.finish = function() {
            return $.Deferred(function(deferred) {
                var backend_connection_info = {'host': '',
                                               'port': 80,
                                               'username': '',
                                               'password': ''};
                if (!self.data.localHost()) {
                    backend_connection_info.host = self.data.host();
                    backend_connection_info.port = self.data.port();
                    backend_connection_info.username = self.data.clientId();
                    backend_connection_info.password = self.data.clientSecret();
                }
                var postData = {
                    backend_info: {
                        domain_guid: self.data.domain() === undefined ? null : self.data.domain().guid(),
                        linked_guid: self.data.albaBackend().guid(),
                        linked_name: self.data.albaBackend().name(),
                        linked_preset: self.data.albaPreset().name,
                        linked_alba_id: self.data.albaBackend().albaId()
                    },
                    backend_connection_info: backend_connection_info
                };
                generic.alertInfo(
                    $.t('alba:wizards.link_backend.started'),
                    $.t('alba:wizards.link_backend.started_msg', {
                        global_backend: self.data.target().name(),
                        backend_to_link: self.data.albaBackend().name()
                    })
                );
                deferred.resolve();
                api.post('alba/backends/' + self.data.target().guid() + '/link_alba_backends', {data: {metadata: postData}})
                    .then(self.shared.tasks.wait)
                    .done(function(data) {
                        if (data === true) {
                            generic.alertSuccess(
                                $.t('alba:wizards.link_backend.success'),
                                $.t('alba:wizards.link_backend.success_msg', {
                                    global_backend: self.data.target().name(),
                                    backend_to_link: self.data.albaBackend().name()
                                })
                            );
                        } else {
                            generic.alertWarning(
                                $.t('alba:wizards.link_backend.in_progress'),
                                $.t('alba:wizards.link_backend.in_progress_msg', {
                                    backend: self.data.albaBackend().name()
                                })
                            );
                        }
                    })
                    .fail(function(error) {
                        error = generic.extractErrorMessage(error);
                        generic.alertError(
                            $.t('ovs:generic.error'),
                            $.t('alba:wizards.link_backend.error_msg', {error: error})
                        );
                    })
            }).promise();
        };
        self.loadAlbaBackends = function() {
            return $.Deferred(function(albaDeferred) {
                generic.xhrAbort(self.loadAlbaBackendsHandle);
                self.invalidAlbaInfo(false);
                self.loadingAlbaBackends(true);

                var relay = '', remoteInfo = {},
                    getData = {
                        backend_type: 'alba',
                        contents: '_dynamics,-ns_data'
                    };
                if (!self.data.localHost()) {
                    relay = 'relay/';
                    remoteInfo.ip = self.data.host();
                    remoteInfo.port = self.data.port();
                    remoteInfo.client_id = self.data.clientId();
                    remoteInfo.client_secret = self.data.clientSecret();
                }
                $.extend(getData, remoteInfo);
                self.loadAlbaBackendsHandle = api.get(relay + 'backends', {queryparams: getData})
                    .done(function(data) {
                        var available_backends = [], calls = [];
                        $.each(data.data, function (index, item) {
                            if (item.available === true && item.linked_guid !== self.data.target().guid()) {
                                calls.push(
                                    api.get(relay + 'alba/backends/' + item.linked_guid + '/', { queryparams: getData })
                                        .then(function(data) {
                                            var alreadyLinked = false, albaBackendDomainMap = {};
                                            if (self.data.localHost()) {  // We only care about domains for backends on the local system
                                                albaBackendDomainMap[data.guid] = generic.keys(data.local_summary['domain_info']);
                                                $.extend(self.albaBackendDomainMap(), albaBackendDomainMap);
                                            }
                                            $.each(data.linked_backend_guids, function(index, guid) {
                                                if (self.data.target().linkedBackendGuids().contains(guid)) {
                                                    alreadyLinked = true;
                                                    return false;
                                                }
                                            });
                                            if (alreadyLinked === false) {
                                                $.each(data.local_summary.devices, function(key, value) {
                                                    if (value > 0) {
                                                        available_backends.push(data);
                                                        self.albaPresetMap()[data.guid] = {};
                                                        $.each(data.presets, function (_, preset) {
                                                            self.albaPresetMap()[data.guid][preset.name] = preset.is_available;
                                                        });
                                                        return false;
                                                    }
                                                });
                                            }
                                        })
                                );
                            }
                        });
                        $.when.apply($, calls)
                            .then(function() {
                                if (available_backends.length > 0) {
                                    var guids = [], abData = {};
                                    $.each(available_backends, function(index, item) {
                                        guids.push(item.guid);
                                        abData[item.guid] = item;
                                    });
                                    generic.crossFiller(
                                        guids, self.data.albaBackends,
                                        function(guid) {
                                            return new AlbaBackend(guid);
                                        }, 'guid'
                                    );
                                    $.each(self.data.albaBackends(), function(index, albaBackend) {
                                        albaBackend.fillData(abData[albaBackend.guid()]);
                                    });
                                    self.data.albaBackends.sort(function(backend1, backend2) {
                                        return backend1.name() < backend2.name() ? -1 : 1;
                                    });
                                    self.data.albaBackend(self.data.albaBackends()[0]);
                                    self.data.albaPreset(self.data.albaBackends()[0].enhancedPresets()[0]);
                                } else {
                                    self.data.albaBackends([]);
                                    self.data.albaBackend(undefined);
                                    self.data.albaPreset(undefined);
                                }
                            })
                            .done(albaDeferred.resolve)
                            .fail(function() {
                                self.data.albaBackends([]);
                                self.data.albaBackend(undefined);
                                self.data.albaPreset(undefined);
                                self.invalidAlbaInfo(true);
                                albaDeferred.reject();
                            })
                            .always(function() {
                                self.loadingAlbaBackends(false);
                            });
                    })
                    .fail(function() {
                        self.data.albaBackends([]);
                        self.data.albaBackend(undefined);
                        self.data.albaPreset(undefined);
                        self.loadingAlbaBackends(false);
                        self.invalidAlbaInfo(true);
                        albaDeferred.reject();
                    });
            }).promise();
        };
        self.loadDomains = function() {
            return $.Deferred(function(deferred) {
                if (generic.xhrCompleted(self.loadDomainsHandle)) {
                    self.loadingDomains(true);
                    self.loadDomainsHandle = api.get('domains', {queryparams: {sort: 'name', contents: ''}})
                        .done(function(data) {
                            var guids = [], ddata = {};
                            $.each(data.data, function(index, item) {
                                guids.push(item.guid);
                                ddata[item.guid] = item;
                            });
                            generic.crossFiller(
                                guids, self.data.domains,
                                function(guid) {
                                    return new Domain(guid);
                                }, 'guid'
                            );
                            $.each(self.data.domains(), function(index, domain) {
                                if (ddata.hasOwnProperty(domain.guid())) {
                                    domain.fillData(ddata[domain.guid()]);
                                }
                            });
                            self.data.domains.sort(function(dom1, dom2) {
                                return dom1.name() < dom2.name() ? -1 : 1;
                            });
                            deferred.resolve();
                        })
                        .fail(deferred.reject)
                        .always(function() {
                            self.loadingDomains(false);
                        });
                } else {
                    deferred.reject();
                }
            }).promise();
        };

        // Durandal
        self.activate = function() {
            self.loadAlbaBackends()
                .then(self.loadDomains);
        };
    };
});
