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
    'jquery', 'knockout',
    'ovs/api', 'ovs/shared', 'ovs/generic',
    'viewmodels/services/albabackend', 'viewmodels/services/storagerouter'
], function($, ko, api, shared, generic,
            albaBackendService, storageRouterService) {
    "use strict";
    return function() {
        var self = this;

        // Variables
        self.shared                   = shared;
        self.loadStorageRoutersHandle = undefined;

        // Observables
        self.scalings                = ko.observableArray(['local', 'global']);
        self.scaling                 = ko.observable('local');
        self.storageRoutersChecked   = ko.observable(false);
        self.validStorageRouterFound = ko.observable();

        // Computed
        self.canContinue = ko.pureComputed(function() {
            var valid = true, reasons = [], fields = [];
            if (self.validStorageRouterFound() === false) {
                valid = false;
                reasons.push($.t('alba:wizards.add_backend.gather.missing_arakoon'));
            }
            if (self.storageRoutersChecked() !== true) {
                valid = false;
            }
            return { value: valid, reasons: reasons, fields: fields };
        });

        self.finish = function(data) {
            return albaBackendService.addAlbaBackend({
                backend_guid: data.guid,
                scaling: self.scaling().toUpperCase()
            })
        };

        // Durandal
        self.activate = function() {
            if (generic.xhrCompleted(self.loadStorageRoutersHandle)) {
                self.loadStorageRoutersHandle = storageRouterService.loadStorageRouters({ contents: '' })
                    .then(function(data) {
                        var subcalls = [];
                        $.each(data.data, function(index, item) {
                            subcalls.push(
                                storageRouterService.getMetadata(item.guid)
                                    .then(function(metadata) {
                                        $.each(metadata.partitions, function(role, partitions) {
                                            if (role === 'DB' && partitions.length > 0) {
                                                self.validStorageRouterFound(true);
                                            }
                                        });
                                        return metadata
                                    }))
                        });
                        $.when.apply($, subcalls)
                            .then(function(){
                                if (self.validStorageRouterFound() === undefined) {
                                    self.validStorageRouterFound(false);
                                }
                            })
                            .always(function() {
                                self.storageRoutersChecked(true);
                            });
                    });
            }
            self.scaling('local');
        };
    };
});
