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
        self.usage       = ko.observable([]);

        // Functions
        self.fillData = function(data) {
            self.name(data.name);
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
                    total += stats.vpools[vpool.guid()].storage;
                    vpools.push({
                        name: $.t('ovs:generic.vpool') + ': ' + vpool.name(),
                        value: stats.vpools[vpool.guid()].storage,
                        percentage: stats.vpools[vpool.guid()].storage / stats.global.size
                    });
                });
                overhead = stats.global.used - total;
                usage = [
                    { name: $.t('alba:generic.stats.freespace'), value: freespace, percentage: freespace / stats.global.size },
                    { name: $.t('alba:generic.stats.unknown'), value: unknown, percentage: unknown / stats.global.size },
                    { name: $.t('alba:generic.stats.overhead'), value: overhead, percentage: overhead / stats.global.size }
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
