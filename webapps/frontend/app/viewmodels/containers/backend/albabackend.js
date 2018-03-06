// Copyright (C) 2016 iNuron NV
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
    'jquery', 'knockout', 'durandal/app',
    'ovs/generic', 'ovs/api', 'ovs/shared',
    'viewmodels/containers/shared/base_container', 'viewmodels/containers/backend/backend',
    'viewmodels/services/backend', 'viewmodels/services/albabackend'
], function($, ko, app, generic, api, shared,
            BaseContainer, Backend,
            backendService, albaBackendService) {
    "use strict";

    var viewModelMapping = {
    };
    /**
     * AlbaBackend class
     * @param guid: Guid of the AlbaBackend
     * @param data: Data of the AlbaBackend
     * @constructor
     */
    function AlbaBackend(guid, data){
        var self = this;
        BaseContainer.call(self);

        // Handles
        self.actionsHandle = undefined;
        self.loadHandle    = undefined;
        self.shared        = shared;

        // Observables
        self.loaded             = ko.observable(false);
        self.loading            = ko.observable(false);
        self.color              = ko.observable(null);
        self.availableActions   = ko.observableArray([]);

        var vmData = $.extend({
            alba_id: null,
            backend: null,
            backend_guid: null,
            color: null,
            guid: guid,
            linked_backend_guids: [],
            presets: [],
            name: null,
            scaling: null,
            local_summary: {},
            usages: {}  // Converted into a viewModel with observables
        }, data || {});

        ko.mapping.fromJS(vmData, viewModelMapping, self);  // Bind the data into this

        // Computed
        self.enhancedPresets = ko.pureComputed(function() {
            return backendService.parsePresets(self.presets().map(function(presetModel) {
                return ko.toJS(presetModel)
            }));
        });
        self.usage = ko.pureComputed(function() {
            if (!(self.usages.size && self.usages.used && self.usages.free)) {
                return []
            }
            var stats = ko.mapping.toJSON(self.usages);
            return [
                {
                    name: $.t('alba:generic.stats.used'),
                    value: stats.used,
                    percentage: stats.size > 0 ? stats.used / stats.size : 0,
                    // Use custom colors for the pie chart
                    color: '#377ca8'
                },
                {
                    name: $.t('alba:generic.stats.freespace'),
                    value: stats.size > 0 ? stats.free : 0.000001,
                    percentage: stats.size > 0 ? stats.free / stats.size : 1
                }
                ];
        });
        self.totalSize = ko.pureComputed(function() {
            if (self.usages.size) {
                return ko.utils.unwrapObservable(self.usages.size)
            }
        })
    }
    var functions = {
        getAvailableActions: function() {
            var self = this;
            return $.when()
                .then(function() {
                    if (!generic.xhrCompleted(self.loadHandle)) {
                        return self.availableActions()
                    }
                    return self.actionsHandle = albaBackendService.getAvailableActions(self.guid())
                        .then(function(data) {
                            self.availableActions(data);
                            return self.availableActions()
                        })
                })
        },
        load: function(contents) {
            var self = this;
            if (contents === undefined) {
                // TODO: Remove collecting all dynamics and all relations on every load action
                contents = '_dynamics,-statistics,-ns_data,-local_stack,_relations';
            }
            self.loading(true);
            return $.when()
                .then(function() {
                    if (!generic.xhrCompleted(self.loadHandle)) {
                        return self
                    }
                    return self.loadHandle = albaBackendService.loadAlbaBackend(self.guid(), { contents: contents })
                        .then(function(data) {
                            self.update(data);
                            return self
                        })
                        .always(function() {
                            self.loading(false);
                        });
                });
        }
    };
    AlbaBackend.prototype = $.extend({}, BaseContainer.prototype, functions);
    return AlbaBackend
});
