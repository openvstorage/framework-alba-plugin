// Copyright 2014 CloudFounders NV
// All rights reserved
/*global define */
define([
    'jquery', 'knockout',
    'ovs/generic', 'ovs/api'
], function($, ko, generic, api) {
    "use strict";
    return function(guid) {
        var self = this;

        // Handles
        self.loadHandle = undefined;

        // Observables
        self.loading           = ko.observable(false);
        self.loaded            = ko.observable(false);
        self.guid              = ko.observable(guid);
        self.serialNumber      = ko.observable();
        self.connectionInfo    = ko.observable();
        self.capacity          = ko.observable();
        self.percentFree       = ko.observable();
        self.networkInterfaces = ko.observableArray([]);

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
        self.liveguid = ko.computed(function() {
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
            self.serialNumber(data.serial_number);
            self.connectionInfo(data.connection_info);
            generic.trySet(self.capacity, data, 'capacity');
            generic.trySet(self.percentFree, data, 'percent_free');
            generic.trySet(self.networkInterfaces, data, 'network_interfaces');

            self.loaded(true);
            self.loading(false);
        };
        self.load = function() {
            return $.Deferred(function(deferred) {
                self.loading(true);
                if (generic.xhrCompleted(self.loadHandle)) {
                    self.loadHandle = api.get('alba/kineticdevices/' + self.guid())
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
