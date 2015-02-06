// Copyright 2014 CloudFounders NV
// All rights reserved
/*global define */
define([
    'jquery', 'durandal/app', 'knockout',
    'ovs/shared', 'ovs/generic', 'ovs/refresher', 'ovs/api',
    '../containers/backend', '../containers/backendtype', '../containers/albabackend',
    '../containers/livekineticdevice', '../containers/osdunit'
], function($, app, ko, shared, generic, Refresher, api, Backend, BackendType, AlbaBackend, LiveKineticDevice, OSDUnit) {
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
            { key: 'capacity',  value: $.t('alba:generic.capacity'),  width: undefined },
            { key: 'actions',   value: $.t('alba:generic.add'),       width: 50        }
        ];
        self.registeredDeviceHeaders = [
            { key: 'id',        value: $.t('alba:generic.id'),        width: 400       },
            { key: 'nrOfDisks', value: $.t('alba:generic.nrofdisks'), width: 200       },
            { key: 'capacity',  value: $.t('alba:generic.capacity'),  width: undefined },
            { key: 'status',    value: $.t('ovs:generic.status'),     width: 50        }
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
        self.loadVPools = function(page) {
            // @TODO: Not yet implemented
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
                            var deviceGuids = [], devices = {}, unitIds = [], units = {}, unitId;
                            $.each(data.data, function(index, item) {
                                deviceGuids.push(item.serialNumber);
                                devices[item.serialNumber] = item;
                                unitId = item.configuration.chassis;
                                if ($.inArray(unitId, unitIds) === -1) {
                                    unitIds.push(unitId);
                                    units[unitId] = {
                                        id: unitId,
                                        nrOfDisks: 0,
                                        capacity: 0
                                    };
                                }
                                units[unitId].nrOfDisks += 1;
                                units[unitId].capacity += parseInt(item.capacity.nominal, 10);
                            });
                            generic.crossFiller(
                                deviceGuids, self.discoveredDevices,
                                function(serialNumber) {
                                    return new LiveKineticDevice(serialNumber);
                                }, 'serialNumber'
                            );
                            $.each(self.discoveredDevices(), function(index, device) {
                                if ($.inArray(device.serialNumber(), deviceGuids) !== -1) {
                                    device.fillData(devices[device.serialNumber()]);
                                }
                            });
                            generic.crossFiller(
                                unitIds, self.discoveredUnits,
                                function(id) {
                                    return new OSDUnit(id);
                                }, 'id'
                            );
                            $.each(self.discoveredUnits(), function(index, unit) {
                                if ($.inArray(unit.id(), unitIds) !== -1) {
                                    unit.fillData(units[unit.id()]);
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
                                var deviceGuids = [], devices = {}, unitIds = [], units = {}, unitId;
                                $.each(data.data, function(index, item) {
                                    deviceGuids.push(item.asd_id);
                                    devices[item.asd_id] = item;
                                    unitId = item.box_id;
                                    if ($.inArray(unitId, unitIds) === -1) {
                                        unitIds.push(unitId);
                                        units[unitId] = {
                                            id: unitId,
                                            nrOfDisks: 0,
                                            capacity: 0
                                        };
                                    }
                                    units[unitId].nrOfDisks += 1;
                                    units[unitId].capacity += 0; // @TODO: Add capacity, OVS-1596
                                });
                                generic.crossFiller(
                                    deviceGuids, self.registeredDevices,
                                    function(serialNumber) {
                                        return new LiveKineticDevice(serialNumber);
                                    }, 'serialNumber'
                                );
                                $.each(self.registeredDevices(), function(index, device) {
                                    if ($.inArray(device.serialNumber(), deviceGuids) !== -1) {
                                        device.fillData(devices[device.serialNumber()]);
                                    }
                                });
                                generic.crossFiller(
                                    unitIds, self.registeredUnits,
                                    function(id) {
                                        return new OSDUnit(id);
                                    }, 'id'
                                );
                                $.each(self.registeredUnits(), function(index, unit) {
                                    if ($.inArray(unit.id(), unitIds) !== -1) {
                                        unit.fillData(units[unit.id()]);
                                    }
                                });
                            })
                            .fail(function () {
                                deferred.reject();
                            });
                    }
                } else {
                    deferred.resolve();
                }
            }).promise();
        };
        self.addUnit = function(id) {
            var devices = [];
            $.each(self.discoveredDevices(), function(i, discoveredDevice) {
                if (discoveredDevice.configuration().chassis === id) {
                    devices.push(discoveredDevice.toJS());
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
