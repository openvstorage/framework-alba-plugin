// Copyright 2015 CloudFounders NV
// All rights reserved
/*global define */
define([
    'knockout'
], function(ko) {
    "use strict";
    return function(id) {
        var self = this;

        // Handles
        self.loadHandle = undefined;

        // Observables
        self.loading   = ko.observable(false);
        self.loaded    = ko.observable(false);
        self.id        = ko.observable(id);
        self.capacity  = ko.observable();
        self.nrOfDisks = ko.observable();

        // Functions
        self.fillData = function(data) {
            self.id(data.id);
            self.capacity(data.capacity);
            self.nrOfDisks(data.nrOfDisks);

            self.loaded(true);
            self.loading(false);
        };
    };
});
