// Copyright 2014 CloudFounders NV
// All rights reserved
/*global define */
define([
    'jquery', 'durandal/app', 'durandal/system', 'knockout',
    'ovs/shared', 'ovs/generic', 'ovs/refresher', 'ovs/api',
    '../containers/backend', '../containers/backendtype', '../containers/albabackend',
    '../containers/kineticdevice', '../containers/livekineticdevice'
], function($, app, system, ko, shared, generic, Refresher, api, Backend, BackendType, AlbaBackend, KineticDevice, LiveKineticDevice) {
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
        self.discoveredUnitHeaders = [
            { key: 'id',        value: $.t('alba:generic.id'),        width: 400       },
            { key: 'nrOfDisks', value: $.t('alba:generic.nrofdisks'), width: 200       },
            { key: 'capacity',  value: $.t('alba:generic.capacity'),  width: 110       },
            { key: 'actions',   value: $.t('alba:generic.add'),       width: 50        }
        ];
        self.registeredDeviceHeaders = [
            { key: 'id',        value: $.t('alba:generic.id'),        width: 400       },
            { key: 'nrOfDisks', value: $.t('alba:generic.nrofdisks'), width: 200       },
            { key: 'capacity',  value: $.t('alba:generic.capacity'),  width: 110       }
        ];
        self.discoveredDevicesHandle = {};
        self.registeredDevicesHandle = {};
        self.devicesHandle           = {};

        // Observables
        self.backend                      = ko.observable();
        self.albaBackend                  = ko.observable();
        self.discoveredUnits              = ko.observableArray([]);
        self.registeredUnits              = ko.observableArray([]);
        self.devices                      = ko.observableArray([]);
        self.devicesInitialLoad           = ko.observable(true);
        self.vPools                       = ko.observableArray([]);
        self.vPoolsInitialLoad            = ko.observable(true);
        self.discoveredDevices            = ko.observableArray([]);
        self.registeredDevices            = ko.observableArray([]);
        self.discoveredDevicesInitialLoad = ko.observable(true);
        self.registeredDevicesInitialLoad = ko.observable(true);

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
                                        data: {
                                            backend_guid: self.backend().guid(),
                                            accesskey: generic.getTimestamp().toString()
                                        }
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
        self.loadDevices = function(page) {
            return $.Deferred(function(deferred) {
                if (generic.xhrCompleted(self.devicesHandle[page])) {
                    var options = {
                        sort: 'name',
                        page: page,
                        contents: '_dynamics'
                    };
                    self.devicesHandle[page] = api.get('alba/kineticdevices', { queryparams: options })
                        .done(function(data) {
                            deferred.resolve({
                                data: data,
                                loader: function(guid) {
                                    return new KineticDevice(guid);
                                }
                            });
                        })
                        .fail(function() { deferred.reject(); });
                } else {
                    deferred.resolve();
                }
            }).promise();
        };
        self.loadVPools = function(page) {
            // Not yet implemented
            return $.Deferred(function(deferred) {
                self.vPoolsInitialLoad(false);
                deferred.resolve();
            }).promise();
        };
        self.loadDiscoveredDevices = function(page, fresh) {
            fresh = (fresh === undefined ? true : fresh);
            return $.Deferred(function(deferred) {
                if (generic.xhrCompleted(self.discoveredDevicesHandle[page])) {
                    var options = {
                        sort: 'name',
                        page: page,
                        contents: '_dynamics',
                        fresh: fresh
                    };
                    self.discoveredDevicesHandle[page] = api.get('alba/livekineticdevices', { queryparams: options })
                        .done(function(data) {
                            var units = [], devices = [];
                            $.each(data.data, function(index, item) {
                                var i, found = false;
                                for (i = 0; i < units.length; i += 1) {
                                    if (item.configuration.chassis === units[i].id) {
                                        found = true;
                                        units[i].nrOfDisks = units[i].nrOfDisks + 1;
                                        units[i].capacity = parseInt(units[i].capacity) + parseInt(item.capacity.nominal);
                                    }
                                }
                                if (found === false) {
                                    units.push({id: item.configuration.chassis,
                                                nrOfDisks: 1,
                                                capacity: item.capacity.nominal});
                                }
                                devices.push(item);
                            });

                            generic.syncObservableArray(devices, self.discoveredDevices, 'serialNumber', true);
                            generic.syncObservableArray(units, self.discoveredUnits, 'id', true);

                            deferred.resolve({
                                data: data,
                                loader: function(serialNumber) {
                                    return new LiveKineticDevice(serialNumber);
                                }
                            });
                        })
                        .fail(function() { deferred.reject(); });
                } else {
                    deferred.resolve();
                                }
            }).promise();
        };
        self.loadRegisteredDevices = function(page, fresh) {
            fresh = (fresh === undefined ? true : fresh);
            return $.Deferred(function(deferred) {
                if (generic.xhrCompleted(self.registeredDevicesHandle[page])) {
                    var options = {
                        sort: 'id',
                        page: page,
                        contents: '_dynamics',
                        fresh: fresh
                    };
                    if (self.albaBackend() !== undefined) {
                        self.registeredDevicesHandle[page] = api.get('alba/backends/' + self.albaBackend().guid() + '/list_osds', {queryparams: options})
                            .done(function (data) {
                                var units = [], devices = [];
                                $.each(data.data, function (index, item) {
                                    var i, found = false;
                                    for (i = 0; i < units.length; i += 1) {
                                        if (item.box_id === units[i].id) {
                                            found = true;
                                            units[i].nrOfDisks = units[i].nrOfDisks + 1;
                                            // @todo: capacity info will be added to the list_osds command
                                            // OVS-1596
                                            units[i].capacity = 0;
                                        }
                                    }
                                    if (found === false) {
                                        units.push({
                                            id: item.box_id,
                                            nrOfDisks: 1,
                                            capacity: 0
                                        });
                                    }
                                    devices.push(item);
                                });

                                generic.syncObservableArray(devices, self.registeredDevices, 'asd_id', true);
                                generic.syncObservableArray(units, self.registeredUnits, 'id', true);
                            })
                            .fail(function () {
                                deferred.reject();
                            });
                    };
                } else {
                    deferred.resolve();
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
                            api.post('alba/backends/' + self.albaBackend().guid() + '/add_device', {
                                data: {
                                    ip: device.nic().ip_address,
                                    port: device.nic().port,
                                    serial: device.serialNumber()
                                }
                            })
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
        self.addUnit = function(id) {
            var devices = [];
            $.each(self.discoveredDevices(), function(i, discoveredDevice) {
               if (discoveredDevice.configuration.chassis === id) {
                   devices.push(discoveredDevice);
               }
            });

            if (devices !== undefined) {
                app.showMessage(
                    $.t('alba:storageunit.add.warning', { what: id }),
                    $.t('ovs:generic.areyousure'),
                    [$.t('ovs:generic.no'), $.t('ovs:generic.yes')]
                )
                    .done(function (answer) {
                        if (answer === $.t('ovs:generic.yes')) {
                            api.post('/alba/backends/' + self.albaBackend().guid() + '/add_unit', {
                                data: {
                                    devices: devices
                                }
                            })
                                .then(self.shared.tasks.wait)
                                .done(function() {
                                        generic.alertSuccess(
                                            $.t('alba:livekinetic.add.done'),
                                            $.t('alba:livekinetic.add.donemsg', { what: id })
                                        );
                                })
                                .fail(function(error) {
                                    generic.alertError(
                                        $.t('ovs:generic.error'),
                                        $.t('ovs:generic.messages.errorwhile', {
                                            context: 'error',
                                            what: $.t('alba:livekinetic.add.errormsg', { what: id }),
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
            //self.load();
            self.loadVPools();
            self.loadDiscoveredDevices(1, false);

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
