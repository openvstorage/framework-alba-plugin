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
        self.putsPerSecond     = ko.deltaObservable(generic.formatNumber);
        self.getsPerSecond     = ko.deltaObservable(generic.formatNumber);

        // Computed
        self.nic = ko.computed(function() {
            if (self.networkInterfaces().length === 0) {
                return undefined;
            }
            self.networkInterfaces.sort(function(a, b) {
                return a.mac_address < b.mac_address;
            });
            return self.networkInterfaces()[0];
        });
        self.guid = ko.computed(function() {
            // The guid in this container object is fake; it contains the ip and port wrapped as a guid for passing
            // to the API. This way, the API can use this ip/port to load certain information.
            var nic = self.nic(), ip, ipParts, port;
            if (nic === undefined) {
                return '00000000-0000-0000-0000-000000000000';
            }
            ip = nic.ip_address;
            ipParts = ip.split('.');
            port = nic.port;
            return generic.padLeft(ipParts[0], '0', 8) + '-' + generic.padLeft(ipParts[1], '0', 4) +
                '-' + generic.padLeft(ipParts[2], '0', 4) + '-' + generic.padLeft(ipParts[3], '0', 4) +
                '-' + generic.padLeft(port.toString(), '0', 12);
        });

        // Functions
        self.fillData = function(data) {
            generic.trySet(self.networkInterfaces, data, 'network_interfaces');
            generic.trySet(self.configuration, data, 'configuration');
            generic.trySet(self.statistics, data, 'statistics');
            generic.trySet(self.capacity, data, 'capacity');
            generic.trySet(self.temperature, data, 'temperature');
            generic.trySet(self.limits, data, 'limits');
            generic.trySet(self.utilization, data, 'utilization');

            //if (data.hasOwnProperty('statistics')) {
            //    self.putsPerSecond(data.statistics.PUT.count);
            //    self.getsPerSecond(data.statistics.GET.count);
            //}

            self.loaded(true);
            self.loading(false);
        };
        self.refresh = function() {
            if (!self.loaded()) {
                return;
            }
            return $.Deferred(function(deferred) {
                self.loading(true);
                if (generic.xhrCompleted(self.loadHandle)) {
                    self.loadHandle = api.get('alba/livekineticdevices/' + self.guid())
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
