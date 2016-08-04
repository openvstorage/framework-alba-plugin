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
    '../../containers/albabackend'
], function($, ko, api, shared, generic, data, AlbaBackend) {
    "use strict";
    return function() {
        var self = this;

        // Variables
        self.data   = data;
        self.shared = shared;

        // Observables
        self.albaBackendLoading = ko.observable(false);
        self.albaPresetMap      = ko.observable({});
        self.invalidAlbaInfo    = ko.observable(false);

        // Handles
        self.loadAlbaBackendsHandle = undefined;

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
        self.canContinue = ko.computed(function() {
            var valid = true, reasons = [], fields = [];
            if (self.invalidAlbaInfo()) {
                valid = false;
                reasons.push($.t('alba:wizards.link_backend.invalid_alba_info'));
                fields.push('clientid');
                fields.push('clientsecret');
                fields.push('host');
            }
            if (self.data.albaBackend() === undefined && self.albaBackendLoading()) {
                valid = false;
                reasons.push($.t('alba:wizards.link_backend.choose_backend'));
                fields.push('backend');
            }
            if (self.data.albaBackend() !== undefined && self.data.albaPreset() === undefined) {
                valid = false;
                reasons.push($.t('alba:wizards.link_backend.choose_preset'));
                fields.push('preset');
            }
            if (!self.isPresetAvailable()) {
                valid = false;
                reasons.push($.t('alba:wizards.link_backend.alba_preset_unavailable'));
                fields.push('preset');
            }
            return { value: valid, reasons: reasons, fields: fields };
        });

        // Functions
        self.finish = function() {
            return $.Deferred(function(deferred) {
                var postData = {
                    backend_connection_info: {
                        host: self.data.host(),
                        port: self.data.port(),
                        username: self.data.clientId(),
                        password: self.data.clientSecret()
                    },
                    backend_info: {
                        linked_guid: self.data.albaBackend().guid(),
                        linked_name: self.data.albaBackend().name(),
                        linked_preset: self.data.albaPreset().name,
                        linked_alba_id: self.data.albaBackend().albaId()
                    }
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
                    .done(function() {
                        generic.alertSuccess(
                            $.t('alba:wizards.link_backend.success'),
                            $.t('alba:wizards.link_backend.success_msg', {
                                global_backend: self.data.target().name(),
                                backend_to_link: self.data.albaBackend().name()
                            })
                        );
                    })
                    .fail(function(error) {
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
                self.albaBackendLoading(true);

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
                                            var alreadyLinked = false;
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
                                self.albaBackendLoading(false);
                            })
                            .done(albaDeferred.resolve)
                            .fail(function() {
                                self.data.albaBackends([]);
                                self.data.albaBackend(undefined);
                                self.data.albaPreset(undefined);
                                self.albaBackendLoading(false);
                                self.invalidAlbaInfo(true);
                                albaDeferred.reject();
                            });
                    })
                    .fail(function() {
                        self.data.albaBackends([]);
                        self.data.albaBackend(undefined);
                        self.data.albaPreset(undefined);
                        self.albaBackendLoading(false);
                        self.invalidAlbaInfo(true);
                        albaDeferred.reject();
                    });
            }).promise();
        };

        // Durandal
        self.activate = function() {
            self.loadAlbaBackends();
        };
    };
});
