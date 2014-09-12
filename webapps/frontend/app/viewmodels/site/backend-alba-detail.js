// Copyright 2014 CloudFounders NV
// All rights reserved
/*global define */
define([
    'jquery', 'durandal/app', 'knockout',
    'ovs/shared', 'ovs/generic', 'ovs/refresher', 'ovs/api',
    '../containers/backend', '../containers/backendtype', '../containers/albabackend',
    '../containers/kineticdevice', '../containers/livekineticdevice'
], function($, app, ko, shared, generic, Refresher, api, Backend, BackendType, AlbaBackend, KineticDevice, LiveKineticDevice) {
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
            { key: 'serial',    value: $.t('alba:generic.serial'),    width: 400       },
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
        self.devicesHandle           = {};

        // Observables
        self.backend                      = ko.observable();
        self.albaBackend                  = ko.observable();
        self.devices                      = ko.observableArray([]);
        self.devicesInitialLoad           = ko.observable(true);
        self.vPools                       = ko.observableArray([]);
        self.vPoolsInitialLoad            = ko.observable(true);
        self.discoveredDevices            = ko.observableArray([]);
        self.discoveredDevicesInitialLoad = ko.observable(true);

        // Computed
        self.availableDevices = ko.computed(function() {
            var devices = [], found;
            $.each(self.discoveredDevices(), function(i, discoveredDevice) {
                found = false;
                $.each(self.devices(), function(j, presentDevice) {
                    if (presentDevice.serialNumber() === discoveredDevice.serialNumber()) {
                        found = true;
                    }
                });
                if (!found) {
                    devices.push(discoveredDevice);
                }
            });
            return devices;
        });

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
        self.refreshDevices = function(page) {
            return $.Deferred(function(deferred) {
                if (generic.xhrCompleted(self.devicesHandle[page])) {
                    var options = { contents: '_dynamics' };
                    if (page !== undefined) {
                        options.page = page;
                    }
                    self.devicesHandle[page] = api.get('alba/kineticdevices', { queryparams: options })
                        .done(function(data) {
                            var guids = [], ddata = {};
                            $.each(data, function(index, item) {
                                guids.push(item.guid);
                                ddata[item.guid] = item;
                            });
                            generic.crossFiller(
                                guids, self.devices,
                                function(guid) {
                                    return new KineticDevice(guid);
                                }, 'guid'
                            );
                            $.each(self.devices(), function(index, device) {
                                if (ddata.hasOwnProperty(device.guid())) {
                                    device.fillData(ddata[device.guid()]);
                                }
                            });
                            self.devicesInitialLoad(false);
                            deferred.resolve();
                        })
                        .fail(deferred.reject);
                } else {
                    deferred.reject();
                }
            }).promise();
        };
        self.refreshVPools = function() {
            // Not yet implemented
            self.vPoolsInitialLoad(false);
        };
        self.refreshDiscoveredDevices = function(page, fresh) {
            fresh = fresh === undefined ? true : fresh;
            return $.Deferred(function(deferred) {
                if (generic.xhrCompleted(self.discoveredDevicesHandle[page])) {
                    var options = {
                        contents: '_dynamics',
                        fresh: fresh
                    };
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
            var device;
            $.each(self.availableDevices(), function(i, availableDevice) {
                if (availableDevice.serialNumber() === serial) {
                    device = availableDevice;
                }
            });
            if (device !== undefined) {
                app.showMessage(
                    $.t('alba:livekinetic.add.warning', { what: serial }),
                    $.t('ovs:generic.areyousure'),
                    [$.t('ovs:generic.no'), $.t('ovs:generic.yes')]
                )
                    .done(function (answer) {
                        if (answer === $.t('ovs:generic.yes')) {
                            api.post('/alba/backends/' + self.albaBackend().guid() + '/add_device', { data: {
                                ip: device.nic().ip_address,
                                port: device.nic().port,
                                serial: device.serialNumber()
                            }})
                                .then(self.shared.tasks.wait)
                                .done(function() {
                                        generic.alertSuccess(
                                            $.t('alba:livekinetic.add.done'),
                                            $.t('alba:livekinetic.add.donemsg', { what: serial })
                                        );
                                    })
                                    .fail(function(error) {
                                        generic.alertError(
                                            $.t('ovs:generic.error'),
                                            $.t('ovs:generic.messages.errorwhile', {
                                                context: 'error',
                                                what: $.t('alba:livekinetic.add.errormsg', { what: serial }),
                                                error: error
                                            })
                                        );
                                    });
                        }
                    });
            }
        };
        self.formatBytes = function(value) {
            return generic.formatBytes(value);
        };
        self.formatPercentage = function(value) {
            return generic.formatPercentage(value);
        };

        // Durandal
        self.activate = function(mode, guid) {
            self.backend(new Backend(guid));

            self.refreshDevices();
            self.refreshVPools();
            self.refreshDiscoveredDevices(undefined, false);

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
