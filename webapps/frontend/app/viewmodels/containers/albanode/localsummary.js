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
    'jquery', 'durandal/app', 'knockout', 'plugins/dialog',
    'ovs/generic', 'ovs/api', 'ovs/shared',
    'viewmodels/containers/shared/base_container', 'viewmodels/containers/albanode/albaslot',
    'viewmodels/wizards/addosd/index', 'viewmodels/wizards/removeosd/index',
    'viewmodels/services/albanodeclusterservice'
], function($, app, ko, dialog,
            generic, api, shared,
            BaseContainer, Slot,
            AddOSDWizard, RemoveOSDWizard,
            albaNodeClusterService) {
    "use strict";
    var viewModelMapping = {};

    /**
     * LocalSummaryModel class
     * @param data: Data to bind into the model. This data maps with model in the Framework
     * @constructor
     */
    function ViewModel(data){
        var self = this;

        // Inherit from base
        BaseContainer.call(self);

        // Variables
        var colourInfoMap = {
            green: {
                tooltip: $.t('alba:generic.states.osdinfo.node.claimed'),
                css: "label label-success pointer"
            },
            orange: {
                tooltip: $.t('alba:generic.states.osdinfo.node.warning'),
                css: "label label-warning pointer"
            },
            red: {
                tooltip: $.t('alba:generic.states.osdinfo.node.error'),
                css: "label label-danger pointer"
            },
            lightgray: {
                tooltip: $.t('alba:generic.states.osdinfo.node.unavailable'),
                css: "label label-unavailable pointer"
            },
            gray: {
                tooltip: $.t('alba:generic.states.osdinfo.node.unknown'),
                css: "label label-missing pointer"
            }
        };

        // Observables
        self.expanded          = ko.observable(false);

        // Default data - replaces fillData - this always creates observables for the passed keys
        // Most of these properties are given by the API but setting them explicitly to have a view of how this model looks
        var vmData = $.extend({
            'red': 0,
            'green': 0,
            'orange': 0,
            'gray': 0,
            'alba_node_guid': null,  // Keep track of parent state for translations
            'alba_node_cluster_guid': null
        }, data);

        ko.mapping.fromJS(vmData, viewModelMapping, self);  // Bind the data into this


        // Computed
        /**
         * Retrieve this object as list of individual objects with styling (used in the GUI)
         */
        self.listView = ko.computed(function(){
            var items = [];
            $.each(Object.keys(colourInfoMap), function(index, item) {
                items.push($.extend({
                    text: self[item]
                }, colourInfoMap[item]))
            })
        });
    }
    return ViewModel
});
