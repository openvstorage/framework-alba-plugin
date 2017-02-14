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
    'jquery', 'knockout', 'durandal/app',
    'ovs/generic', 'ovs/api', 'ovs/shared',
    '../containers/backend'
], function($, ko, app, generic, api, shared, Backend) {
    "use strict";
    return function(guid) {
        var self = this;

        // Handles
        self.actionsHandle = undefined;
        self.loadHandle    = undefined;
        self.rawData       = undefined;
        self.shared        = shared;

        // Observables
        self.albaId             = ko.observable();
        self.availableActions   = ko.observableArray([]);
        self.backend            = ko.observable();
        self.backendGuid        = ko.observable();
        self.color              = ko.observable();
        self.guid               = ko.observable(guid);
        self.linkedBackendGuids = ko.observableArray();
        self.loaded             = ko.observable(false);
        self.loading            = ko.observable(false);
        self.localSummary       = ko.observable();
        self.name               = ko.observable();
        self.presets            = ko.observableArray([]);
        self.scaling            = ko.observable();
        self.totalSize          = ko.observable();
        self.usage              = ko.observable([]);

        // Computed
        self.enhancedPresets = ko.computed(function() {
            var presets = [], policies, newPolicy, isAvailable, isActive, inUse,
                policyMapping = ['grey', 'black', 'green'], worstPolicy, replication, policyObject;
            $.each(self.presets(), function(index, preset) {
                worstPolicy = 0;
                policies = [];
                replication = undefined;
                $.each(preset.policies, function(jndex, policy) {
                    policyObject = JSON.parse(policy.replace('(', '[').replace(')', ']'));
                    isAvailable = preset.policy_metadata[policy].is_available;
                    isActive = preset.policy_metadata[policy].is_active;
                    inUse = preset.policy_metadata[policy].in_use;
                    newPolicy = {
                        text: policy,
                        color: 'grey',
                        isActive: false,
                        k: policyObject[0],
                        m: policyObject[1],
                        c: policyObject[2],
                        x: policyObject[3]
                    };
                    if (isAvailable) {
                        newPolicy.color = 'black';
                    }
                    if (isActive) {
                        newPolicy.isActive = true;
                    }
                    if (inUse) {
                        newPolicy.color = 'green';
                    }
                    worstPolicy = Math.max(policyMapping.indexOf(newPolicy.color), worstPolicy);
                    policies.push(newPolicy);
                });
                if (preset.policies.length === 1) {
                    policyObject = JSON.parse(preset.policies[0].replace('(', '[').replace(')', ']'));
                    if (policyObject[0] === 1 && policyObject[0] + policyObject[1] === policyObject[3] && policyObject[2] === 1) {
                        replication = policyObject[0] + policyObject[1];
                    }
                }
                presets.push({
                    policies: policies,
                    name: preset.name,
                    compression: preset.compression,
                    fragSize: preset.fragment_size,
                    encryption: preset.fragment_encryption,
                    color: policyMapping[worstPolicy],
                    inUse: preset.in_use,
                    isDefault: preset.is_default,
                    replication: replication
                });
            });
            return presets.sort(function(preset1, preset2) {
                return preset1.name.toLowerCase() < preset2.name.toLowerCase() ? -1 : 1;
            });
        });

        // Functions
        self.getAvailableActions = function() {
            return $.Deferred(function(deferred) {
                if (generic.xhrCompleted(self.actionsHandle)) {
                    self.actionsHandle = api.get('alba/backends/' + self.guid() + '/get_available_actions')
                        .done(function(data) {
                            self.availableActions(data);
                            deferred.resolve();
                        })
                        .fail(deferred.reject);
                } else {
                    deferred.reject();
                }
            }).promise();
        };
        self.fillData = function(data) {
            self.name(data.name);
            self.albaId(data.alba_id);
            self.scaling(data.scaling);
            generic.trySet(self.presets, data, 'presets');
            generic.trySet(self.localSummary, data, 'local_summary');
            if (self.backendGuid() !== data.backend_guid) {
                self.backendGuid(data.backend_guid);
                self.backend(new Backend(data.backend_guid));
            }
            if (data.hasOwnProperty('linked_backend_guids')) {
                self.linkedBackendGuids(data.linked_backend_guids);
            }
            if (data.hasOwnProperty('usages')) {
                var stats = data.usages;
                self.totalSize(stats.size);
                self.usage([
                    {
                        name: $.t('alba:generic.stats.freespace'),
                        value: stats.size > 0 ? stats.free : 0.000001,
                        percentage: stats.size > 0 ? stats.free / stats.size : 1
                    },
                    {
                        name: $.t('alba:generic.stats.used'),
                        value: stats.used,
                        percentage: stats.size > 0 ? stats.used / stats.size : 0
                    }
                ]);
            }
            self.rawData = data;
            self.loaded(true);
            self.loading(false);
        };
        self.load = function(contents) {
            if (contents === undefined) {
                contents = '_dynamics,-statistics,-ns_data,_relations';
            }
            return $.Deferred(function(deferred) {
                self.loading(true);
                if (generic.xhrCompleted(self.loadHandle)) {
                    self.loadHandle = api.get('alba/backends/' + self.guid(), { queryparams: { contents: contents } })
                        .done(function(data) {
                            self.fillData(data);
                            deferred.resolve();
                        })
                        .fail(function() {
                            deferred.reject();
                        })
                        .always(function() {
                            self.loading(false);
                        });
                } else {
                    deferred.reject();
                }
            }).promise();
        };
        self.claimOSDs = function(osdsToClaim) {
            return $.Deferred(function(deferred) {
                var asdIDs = [], asdData = {}, allAsds = [];
                $.each(osdsToClaim, function(diskGuid, asds) {
                    $.each(asds, function(index, asd) {
                        allAsds.push(asd);
                        asdIDs.push(asd.osdID());
                        asdData[asd.osdID()] = diskGuid;
                        asd.processing(true);
                    });
                });
                app.showMessage(
                    $.t('alba:osds.claim.warning', { what: '<ul><li>' + asdIDs.join('</li><li>') + '</li></ul>', multi: allAsds.length === 1 ? '' : 's' }).trim(),
                    $.t('alba:osds.claim.title', {multi: allAsds.length === 1 ? '' : 's'}),
                    [$.t('ovs:generic.yes'), $.t('ovs:generic.no')]
                )
                    .done(function(answer) {
                        if (answer === $.t('ovs:generic.yes')) {
                            if (allAsds.length === 1) {
                                generic.alertInfo(
                                    $.t('alba:osds.claim.started'),
                                    $.t('alba:osds.claim.started_msg_single', {what: allAsds[0].osdID()})
                                );
                            } else {
                                generic.alertInfo(
                                    $.t('alba:osds.claim.started'),
                                    $.t('alba:osds.claim.started_msg_multi')
                                );
                            }
                            api.post('alba/backends/' + self.guid() + '/add_units', {
                                data: { osds: asdData }
                            })
                                .then(self.shared.tasks.wait)
                                .done(function(data) {
                                    if (data.length === 0) {
                                        if (allAsds.length === 1) {
                                            generic.alertSuccess(
                                                $.t('alba:osds.claim.complete'),
                                                $.t('alba:osds.claim.success_single', {what: allAsds[0].osdID()})
                                            );
                                        } else {
                                            generic.alertSuccess(
                                                $.t('alba:osds.claim.complete'),
                                                $.t('alba:osds.claim.success_multi')
                                            );
                                        }
                                    } else {
                                        if (allAsds.length === 1 || allAsds.length === data.length) {
                                            generic.alertError(
                                                $.t('alba:osds.claim.failed_already_claimed'),
                                                $.t('alba:osds.claim.failed_already_claimed_all')
                                            );
                                        } else {
                                            generic.alertWarning(
                                                $.t('alba:osds.claim.warning_already_claimed'),
                                                $.t('alba:osds.claim.warning_already_claimed_some', {requested: allAsds.length, actual: data.length})
                                            );
                                        }
                                    }
                                    $.each(allAsds, function(index, asd) {
                                        asd.ignoreNext(true);
                                        asd.status('claimed');
                                        asd.processing(false);
                                    });
                                    deferred.resolve();
                                })
                                .fail(function(error) {
                                    error = generic.extractErrorMessage(error);
                                    generic.alertError(
                                        $.t('ovs:generic.error'),
                                        $.t('alba:osds.claim.failed', { multi: allAsds.length === 1 ? '' : 's', why: error })
                                    );
                                    $.each(allAsds, function(index, asd) {
                                        asd.processing(false);
                                    });
                                    deferred.reject();
                                });
                        } else {
                            $.each(allAsds, function(index, asd) {
                                asd.processing(false);
                            });
                            deferred.reject();
                        }
                    })
                    .fail(function() {
                        $.each(allAsds, function(index, asd) {
                            asd.processing(false);
                        });
                        deferred.reject();
                    });
            }).promise();
        };
    };
});
