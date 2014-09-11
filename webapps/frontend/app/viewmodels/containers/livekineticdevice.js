// Copyright 2014 CloudFounders NV
// All rights reserved
/*global define */
define([
    'jquery', 'knockout',
    'ovs/generic', 'ovs/api'
], function($, ko, generic, api) {
    "use strict";
    return function(serialNumber) {
        var self = this;

        // Handles
        self.loadHandle = undefined;

        // Observables
        self.loading           = ko.observable(false);
        self.loaded            = ko.observable(false);
        self.serialNumber      = ko.observable(serialNumber);
        self.networkInterfaces = ko.observableArray([]);
        self.statistics        = ko.observable();
        self.capacity          = ko.observable();
        self.temperature       = ko.observable();
        self.limits            = ko.observable();
        self.utilization       = ko.observable();
        self.configuration     = ko.observable();

        // Computed
        self.guid = ko.computed(function() {
            if (self.networkInterfaces.length === 0) {
                return '00000000-0000-0000-0000-000000000000';
            }
            var ip = self.networkInterfaces()[0].ip_address,
                ipParts = ip.split('.'),
                port = self.networkInterfaces()[0].port;
            return generic.padLeft(ipParts[0], '0', 8) + '-' + generic.padLeft(ipParts[1], '0', 4) +
                '-' + generic.padLeft(ipParts[2], '0', 4) + '-' + generic.padLeft(ipParts[3], '0', 4) +
                '-' + generic.padLeft(port, '0', 12);
        });

        // Functions
        self.fillData = function(data) {
            generic.trySet(self.networkInterfaces, data, 'network_interfaces');
            generic.trySet(self.statistics, data, 'statistics');
            generic.trySet(self.capacity, data, 'capacity');
            generic.trySet(self.temperature, data, 'temperature');
            generic.trySet(self.limits, data, 'limits');
            generic.trySet(self.utilization, data, 'utilization');
            generic.trySet(self.configuration, data, 'configuration');

            self.loaded(true);
            self.loading(false);
        };
        self.load = function() {
            return $.Deferred(function(deferred) {
                self.loading(true);
                if (generic.xhrCompleted(self.loadHandle)) {
                    self.loadHandle = api.get('alba/livekineticdrives/' + self.guid())
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
