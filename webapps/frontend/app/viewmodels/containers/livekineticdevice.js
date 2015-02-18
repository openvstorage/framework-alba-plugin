// Copyright 2014 CloudFounders NV
// All rights reserved
/*global define */
define([
    'jquery', 'knockout',
    'ovs/generic'
], function($, ko, generic) {
    "use strict";
    return function(id) {
        var self = this;

        // Handles
        self.loadHandle = undefined;

        // Observables
        self.loading           = ko.observable(false);
        self.loaded            = ko.observable(false);
        self.id                = ko.observable(id);
        self.unit_id           = ko.observable();
        self.networkInterfaces = ko.observableArray([]);
        self.statistics        = ko.observable();
        self.capacity          = ko.observable();
        self.temperature       = ko.observable();
        self.limits            = ko.observable();
        self.utilization       = ko.observable();
        self.configuration     = ko.observable();
        self.putsPerSecond     = ko.deltaObservable(generic.formatNumber);
        self.getsPerSecond     = ko.deltaObservable(generic.formatNumber);

        // Functions
        self.fillData = function(data) {
            self.unit_id(data.box_id);
            generic.trySet(self.networkInterfaces, data, 'network_interfaces');
            generic.trySet(self.configuration, data, 'configuration');
            generic.trySet(self.statistics, data, 'statistics');
            generic.trySet(self.capacity, data, 'capacity');
            generic.trySet(self.temperature, data, 'temperature');
            generic.trySet(self.limits, data, 'limits');
            generic.trySet(self.utilization, data, 'utilization');

            self.loaded(true);
            self.loading(false);
        };
        self.toJS = function() {
            var js = ko.toJS(self);
            js.network_interfaces = js.networkInterfaces;
            delete js.networkInterfaces;
            return js;
        };
    };
});
