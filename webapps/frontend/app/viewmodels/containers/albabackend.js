// Copyright 2014 iNuron NV
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
define([
    'jquery', 'knockout',
    'ovs/generic', 'ovs/api',
    '../containers/backend'
], function($, ko, generic, api, Backend) {
    "use strict";
    return function(guid) {
        var self = this;

        // Handles
        self.loadHandle    = undefined;
        self.actionsHandle = undefined;

        // External dependencies
        self.vPools = undefined;
        self.license = ko.observable();

        // Observables
        self.loading          = ko.observable(false);
        self.loaded           = ko.observable(false);
        self.guid             = ko.observable(guid);
        self.name             = ko.observable();
        self.backend          = ko.observable();
        self.backendGuid      = ko.observable();
        self.color            = ko.observable();
        self.readIOps         = ko.observable(0).extend({ smooth: {} }).extend({ format: generic.formatNumber });
        self.writeIOps        = ko.observable(0).extend({ smooth: {} }).extend({ format: generic.formatNumber });
        self.usage            = ko.observable([]);
        self.presets          = ko.observableArray([]);
        self.availableActions = ko.observableArray([]);

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
                        x: policyObject[3],
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
                    encryption: preset.fragment_encryption,
                    color: policyMapping[worstPolicy],
                    inUse: preset.in_use,
                    isDefault: preset.is_default,
                    replication: replication
                });
            });
            return presets;
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
            generic.trySet(self.presets, data, 'presets');
            if (self.backendGuid() !== data.backend_guid) {
                self.backendGuid(data.backend_guid);
                self.backend(new Backend(data.backend_guid));
            }
            if (data.hasOwnProperty('statistics')) {
                self.readIOps(data.statistics.multi_get.n_ps);
                self.writeIOps(data.statistics.apply.n_ps);
            }
            if (data.hasOwnProperty('ns_statistics') && self.vPools !== undefined) {
                var stats = data.ns_statistics,
                    usage, freespace, unknown, overhead, vpools = [], total = 0;
                freespace = stats.global.size - stats.global.used;
                unknown = stats.unknown.storage;
                $.each(self.vPools(), function(index, vpool) {
                    if (stats.vpools.hasOwnProperty(vpool.guid())) {
                        total += stats.vpools[vpool.guid()].storage;
                        vpools.push({
                            name: $.t('ovs:generic.vpool') + ': ' + vpool.name(),
                            value: stats.vpools[vpool.guid()].storage,
                            percentage: stats.global.size > 0 ? stats.vpools[vpool.guid()].storage / stats.global.size : 0
                        });
                    }
                });
                overhead = Math.max(stats.global.used - total, 0);
                usage = [
                    {
                        name: $.t('alba:generic.stats.freespace'),
                        value: stats.global.size > 0 ? freespace : 0.000001,
                        percentage: stats.global.size > 0 ? freespace / stats.global.size : 1
                    },
                    {
                        name: $.t('alba:generic.stats.unknown'),
                        value: unknown,
                        percentage: stats.global.size > 0 ? unknown / stats.global.size : 0
                    },
                    {
                        name: $.t('alba:generic.stats.overhead'),
                        value: overhead,
                        percentage: stats.global.size > 0 ? overhead / stats.global.size : 0
                    }
                ].concat(vpools);
                self.usage(usage);
            } else {
                self.usage([]);
            }

            self.loaded(true);
            self.loading(false);
        };
        self.load = function() {
            return $.Deferred(function(deferred) {
                self.loading(true);
                if (generic.xhrCompleted(self.loadHandle)) {
                    self.loadHandle = api.get('alba/backends/' + self.guid(), { queryparams: { contents: '_dynamics,_relations' } })
                        .done(function(data) {
                            self.fillData(data);
                            deferred.resolve(data);
                        })
                        .fail(deferred.reject)
                        .always(function() {
                            self.loading(false);
                        });
                } else {
                    deferred.reject();
                }
            }).promise();
        };
    };
});
