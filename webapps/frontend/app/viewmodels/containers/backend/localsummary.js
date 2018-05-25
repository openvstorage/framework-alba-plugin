// Copyright (C) 2018 iNuron NV
//
// This file is part of Open vStorage Open Source Edition (OSE),
// as available from
//
//      http://www.openvstorage.org and
//      http://www.openvstorage.com.
//
// This file is free software; you can redistribute it and/or modify it
// under the terms of the GNU Affero General Public License v3 (GNU AGPLv3)
// as published by the Free Software Foundation, in version 3 as it comes
// in the LICENSE.txt file of the Open vStorage OSE distribution.
//
// Open vStorage is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY of any kind.
/*global define */
define([
    'jquery', 'knockout',
    'viewmodels/containers/shared/base_container'
], function($, ko,
            BaseContainer) {
    "use strict";
    var viewModelMapping = {};

    /**
     * LocalSummaryModel class
     * @param data: Data to bind into the model. This data maps with model in the Framework
     * @constructor
     */
    function LocalSummary(data){
        var self = this;

        // Inherit from base
        BaseContainer.call(self);

        // Observables
        self.expanded = ko.observable(false);

        // Default data - replaces fillData - this always creates observables for the passed keys
        // Most of these properties are given by the API but setting them explicitly to have a view of how this model looks
        var vmData = $.extend(vmData, {
            backend_guid: null,
            devices: {},
            domain_info: {},
            name: null,
            sizes: {},
            scaling: null
        }, data || {});

        ko.mapping.fromJS(vmData, viewModelMapping, self);  // Bind the data into this

        // Computed
        /**
         * Retrieve this object as list of individual objects with styling (used in the GUI)
         */
        self.listView = ko.pureComputed(function(){
            var map = self.colourInfoMap();
            return $.map(map, function(value, key) {
                return $.extend({
                    text: ko.utils.unwrapObservable(self.devices[key]) || 0
                }, map[key])
            })
        });

        self.colourInfoMap = ko.pureComputed(function() {
            var scaling = self.scaling() || '';
            scaling = scaling.toLowerCase();
            return Object.freeze({  // Order matters for display in the GUI
                green: {
                    tooltip: $.t('alba:generic.states.osdinfo.' + scaling + '.claimed'),
                    css: "label label-success pointer"
                },
                orange: {
                    tooltip: $.t('alba:generic.states.osdinfo.' + scaling + '.warning'),
                    css: "label label-warning pointer"
                },
                red: {
                    tooltip: $.t('alba:generic.states.osdinfo.' + scaling + '.error'),
                    css: "label label-danger pointer"
                },
                // lightgray: {
                //     tooltip: $.t('alba:generic.states.osdinfo.' + scaling + '.unavailable'),
                //     css: "label label-unavailable pointer"
                // },
                gray: {
                    tooltip: $.t('alba:generic.states.osdinfo.' + scaling + '.unknown'),
                    css: "label label-missing pointer"
                }
            });
        });
        self.canDisplay = ko.pureComputed(function() {
            return !!ko.utils.unwrapObservable(self.scaling);
        })
    }
    // Prototypical inheritance
    LocalSummary.prototype = $.extend({}, BaseContainer.prototype);
    return LocalSummary
});
