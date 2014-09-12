// Copyright 2014 CloudFounders NV
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
/*global define */
define([
    'jquery', 'knockout',
    'ovs/shared', 'ovs/generic', 'ovs/refresher', 'ovs/api',
    '../containers/livekineticdevice'
], function($, ko, shared, generic, Refresher, api, LiveKineticDevice) {
    "use strict";
    return function() {
        var self = this;

        // Variables
        self.shared     = shared;
        self.guard      = { authenticated: true };
        self.refresher  = new Refresher();
        self.widgets    = [];
        self.nicHeaders = [
            { key: 'interface',  value: $.t('alba:generic.interface'),  width: 110       },
            { key: 'macaddress', value: $.t('alba:generic.macaddress'), width: 200       },
            { key: 'ipaddress',  value: $.t('alba:generic.ipaddress'),  width: undefined }
        ];

        // Observables
        self.deviceGuid = ko.observable();
        self.device     = ko.observable();

        // Computed
        self.loaded = ko.computed(function() {
            return self.device() !== undefined && self.device().loaded();
        });
        self.loading = ko.computed(function() {
            return !self.loaded();
        });

        // Functions
        self.load = function() {
            return $.Deferred(function (deferred) {
                api.get('alba/livekineticdevices/' + self.deviceGuid())
                    .done(function(data) {
                        var device = new LiveKineticDevice(data.configuration.serialNumber);
                        self.device(device);
                        device.fillData(data);
                        deferred.resolve();
                    })
            }).promise();
        };
        self.refresh = function() {
            if (self.device() !== undefined) {
                self.device().refresh();
            }
        };
        self.refreshNics = function() {
            // Not un use, for mapping only
        };
        self.formatBytes = function(value) {
            return generic.formatBytes(value);
        };
        self.formatPercentage = function(value) {
            return generic.formatPercentage(value);
        };

        // Durandal
        self.activate = function(mode, guid) {
            self.deviceGuid(guid);
            self.load();
            self.refresher.init(self.refresh, 5000);
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
