// Copyright 2014 CloudFounders NV
// All rights reserved
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
        self.loadHandle = undefined;

        // External dependencies
        self.vPools = undefined;
        self.license = ko.observable();

        // Observables
        self.loading     = ko.observable(false);
        self.loaded      = ko.observable(false);
        self.guid        = ko.observable(guid);
        self.name        = ko.observable();
        self.backend     = ko.observable();
        self.backendGuid = ko.observable();
        self.color       = ko.observable();
        self.readIOps    = ko.observable(0).extend({ smooth: {} }).extend({ format: generic.formatNumber });
        self.writeIOps   = ko.observable(0).extend({ smooth: {} }).extend({ format: generic.formatNumber });
        self.licenseInfo = ko.observable();
        self.usage       = ko.observable([]);
        self.policies    = ko.observableArray([]);
        self.safety      = ko.observable();

        // Computed
        self.enhancedPolicies = ko.computed(function() {
            var policies = [], newPolicy, isRW, isRO, isActive, isUsed;
            if (self.safety() !== undefined) {
                $.each(self.policies(), function (index, policy) {
                    isRW = policy.nestedIn(self.safety().rw_policies);
                    isRO = policy.nestedIn(self.safety().ro_policies);
                    isActive = policy.equals(self.safety().active_policy);
                    isUsed = policy.nestedIn(self.safety().used_policies);
                    newPolicy = {
                        text: JSON.stringify(policy),
                        color: 'grey',
                        inUse: false
                    };
                    if (isRW) {
                        newPolicy.color = 'black';
                    }
                    if (isActive) {
                        newPolicy.color = 'green';
                    }
                    if (isUsed) {
                        newPolicy.inUse = true;
                        if (isRO) {
                            newPolicy.color = 'orange';
                        } else if (!isRW) {
                            newPolicy.color = 'red';
                        }
                    }
                    policies.push(newPolicy);
                });
            }
            return policies;
        });
        self.configurable = ko.computed(function() {
            var license = self.license(), licenseData, licenseInfo = self.licenseInfo();
            if (license === undefined || licenseInfo === undefined) {
                return false;
            }
            if (license.validUntil() !== null && license.validUntil() * 1000 < generic.getTimestamp()) {
                return false;
            }
            licenseData = license.data();
            return !((licenseData.namespaces !== null && licenseInfo.namespaces >= licenseData.namespaces) ||
                     (licenseData.nodes !== null && licenseInfo.nodes >= licenseData.nodes) ||
                     (licenseData.osds !== null && licenseInfo.asds >= licenseData.osds));
        });

        // Functions
        self.fillData = function(data) {
            self.name(data.name);
            generic.trySet(self.licenseInfo, data, 'license_info');
            generic.trySet(self.policies, data, 'policies');
            generic.trySet(self.safety, data, 'safety');
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
