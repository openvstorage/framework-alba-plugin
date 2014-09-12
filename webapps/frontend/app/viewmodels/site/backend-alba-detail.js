// Copyright 2014 CloudFounders NV
// All rights reserved
/*global define */
define([
    'jquery', 'knockout',
    'ovs/shared', 'ovs/generic', 'ovs/refresher', 'ovs/api',
    '../containers/backend', '../containers/backendtype', '../containers/albabackend',
    '../containers/livekineticdevice'
], function($, ko, shared, generic, Refresher, api, Backend, BackendType, AlbaBackend, LiveKineticDevice) {
    "use strict";
    return function() {
        var self = this;

        // Variables
        self.shared        = shared;
        self.guard         = { authenticated: true };
        self.refresher     = new Refresher();
        self.widgets       = [];
        self.initializing  = false;
        self.deviceHeaders = [
            { key: 'serial',    value: $.t('alba:generic.serial'),    width: 250       },
            { key: 'ips',       value: $.t('alba:generic.ips'),       width: 200       },
            { key: 'capacity',  value: $.t('alba:generic.capacity'),  width: 110       },
            { key: 'freespace', value: $.t('alba:generic.freespace'), width: undefined },
            { key: 'status',    value: $.t('ovs:generic.status'),     width: 50        }
        ];
        self.vPoolHeaders  = [
            { key: 'name',       value: $.t('ovs:generic.name'),       width: undefined },
            { key: 'storedData', value: $.t('ovs:generic.storeddata'), width: 150       },
            { key: 'vmachines',  value: $.t('ovs:generic.vmachines'),  width: 100       },
            { key: 'vdisks',     value: $.t('ovs:generic.vdisks'),     width: 100       },
            { key: 'getss',      value: $.t('alba:generic.getss'),     width: 150       },
            { key: 'putss',      value: $.t('alba:generic.putss'),     width: 100       }
        ];
        self.discoveredDeviceHeaders = [
            { key: 'serial',   value: $.t('alba:generic.serial'),    width: 400       },
            { key: 'ips',      value: $.t('alba:generic.ips'),       width: 200       },
            { key: 'capacity', value: $.t('alba:generic.capacity'),  width: 110       },
            { key: 'model',    value: $.t('alba:generic.model'),     width: undefined },
            { key: 'actions',  value: $.t('alba:generic.add'),       width: 50        }
        ];
        self.discoveredDevicesHandle = {};

        // Observables
        self.backend                      = ko.observable();
        self.albaBackend                  = ko.observable();
        self.devices                      = ko.observableArray([]);
        self.devicesInitialLoad           = ko.observable(true);
        self.vPools                       = ko.observableArray([]);
        self.vPoolsInitialLoad            = ko.observable(true);
        self.discoveredDevices            = ko.observableArray([]);
        self.discoveredDevicesInitialLoad = ko.observable(true);

        // Functions
        self.load = function() {
            return $.Deferred(function (deferred) {
                var backend = self.backend(), backendType;
                backend.load()
                    .then(function(backendData) {
                        return $.Deferred(function(subDeferred) {
                            if (backend.backendType() === undefined) {
                                backendType = new BackendType(backend.backendTypeGuid());
                                backendType.load();
                                backend.backendType(backendType);
                            }
                            if (backendData.hasOwnProperty('alba_backend_guid') && backendData.alba_backend_guid !== null) {
                                if (self.albaBackend() === undefined) {
                                    self.albaBackend(new AlbaBackend(backendData.alba_backend_guid));
                                }
                                subDeferred.resolve(self.albaBackend());
                            } else {
                                if (!self.initializing) {
                                    self.initializing = true;
                                    api.post('alba/backends', {
                                        backend_guid: self.backend().guid(),
                                        accesskey: generic.getTimestamp().toString()
                                    })
                                        .fail(function() {
                                            self.initializing = false;
                                        });
                                }
                                subDeferred.reject();
                            }
                        }).promise();
                    })
                    .then(function(albaBackend) {
                        return albaBackend.load();
                    })
                    .always(deferred.resolve);
            }).promise();
        };
        self.refreshDevices = function() {
            // Not yet implemented
            self.devicesInitialLoad(false);
        };
        self.refreshVPools = function() {
            // Not yet implemented
            self.vPoolsInitialLoad(false);
        };
        self.refreshDiscoveredDevices = function(page) {
            return $.Deferred(function(deferred) {
                if (generic.xhrCompleted(self.discoveredDevicesHandle[page])) {
                    var options = { contents: '_dynamics' };
                    if (page !== undefined) {
                        options.page = page;
                    }
                    self.discoveredDevicesHandle[page] = api.get('alba/livekineticdevices', { queryparams: options })
                        .done(function(data) {
                            var serials = [], kdata = {};
                            $.each(data, function(index, item) {
                                serials.push(item.configuration.serialNumber);
                                kdata[item.configuration.serialNumber] = item;
                            });
                            generic.crossFiller(
                                serials, self.discoveredDevices,
                                function(serialNumber) {
                                    return new LiveKineticDevice(serialNumber);
                                }, 'serialNumber'
                            );
                            $.each(self.discoveredDevices(), function(index, device) {
                                if (kdata.hasOwnProperty(device.serialNumber())) {
                                    device.fillData(kdata[device.serialNumber()]);
                                }
                            });
                            self.discoveredDevicesInitialLoad(false);
                            deferred.resolve();
                        })
                        .fail(deferred.reject);
                } else {
                    deferred.reject();
                }
            }).promise();
        };
        self.addDevice = function(serial) {
            // Not yet implemented
        };
        self.formatBytes = function(value) {
            return generic.formatBytes(value);
        };

        // Durandal
        self.activate = function(mode, guid) {
            self.backend(new Backend(guid));

            self.refresher.init(self.load, 5000);
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
