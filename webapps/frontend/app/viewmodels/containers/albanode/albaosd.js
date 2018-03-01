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
    'durandal/app', 'knockout', 'jquery',
    'ovs/generic',
    'viewmodels/containers/shared/base_container'
], function(app, ko, $,
            generic,
            BaseContainer) {
    "use strict";

    var viewModelMapping = {

    };

    /**
     * AlbaOSD viewModel
     * @param data: Data about the model (see vmData for layout). Similar to the data retrieved from the API
     */
    function viewModel(data) {
        var self = this;
        BaseContainer.call(self);

        // Enums
        self.errorStatuses = Object.freeze({
            warning: 'warning',
            error: 'error',
            unavailable: 'unavailable',
            unknown: 'unknown'
        });
        self.statusses = Object.freeze($.extend({
            available: 'available',
            claimed: 'claimed',
            nodedown: 'nodedown',
            unknown: 'unknown'
        }, self.errorStatuses));

        // Observables
        self._status = ko.observable();
        self.loaded = ko.observable(false);

        var vmData = $.extend({
            alba_backend_guid: null,  // Guid of the viewModel of the detail page (if any),
            claimed_by: null,
            slot_id: null,
            guid: null,
            status_detail: null,
            osd_id: null,
            usage: null,
            device: null,
            mountpount: null,
            port: null,
            ips: [],
            type: null,
            status: null,  // One of the self.statusses options
            node_id: null
        }, data);

        ko.mapping.fromJS(vmData, viewModelMapping, self);  // Bind the data into this
        self.loaded(true);

        // Computed
        self.status = ko.computed({
            deferEvaluation: true,  // Wait with computing for an actual subscription
            read: function() {
                if (Object.values(self.errorStatuses).contains(self.status())) {
                    return self._status();
                }
                if ([null, undefined].contains(self.claimed_by())) {
                    return self.statusses.available;
                }
                return self.claimed_by() === self.alba_backend_guid() ? self.statusses.claimed : self.errorStatuses.unavailable;
            },
            write: function(status) {
                self._status(status)
            }
        });
        self.isLocal = ko.pureComputed(function() {
            return [null, undefined].contains(self.claimed_by()) || self.alba_backend_guid() === self.claimed_by();
        });
        self.locked = ko.pureComputed(function() {
            return [self.statusses.nodedown, self.statusses.unknown].contains(self.statusDetail()) || !self.isLocal();
        });
        self.marked = ko.pureComputed(function() {
            return (self.status() === self.errorStatuses.unavailable || (!self.isLocal() && (self.status() === self.errorStatuses.warning || self.status() === self.errorStatuses.error))) && self.albaBackend() !== undefined;
        });
        self.sockets = ko.pureComputed(function() {
            var sockets = [];
            $.each(self.ips(), function(index, ip) {
               sockets.push(ip + ":" + self.port())
            });
            return sockets
        });

        // Event
        // @todo replace these functions with events (if possible because its wizards)
        // Functions
        self.claim = function() {
            throw new Error('To be done')
            var data = {};
            data[self.slotID()] = {slot: self.slot, osds: [self]};
            self.nodeOrCluster.claimOSDs(data);
        };
        self.remove = function() {
            throw new Error('To be done')
            self.nodeOrCluster.removeOSD(self);
        };
        self.restart = function() {
            throw new Error('To be done')
            self.nodeOrCluster.restartOSD(self);
        };
    }
    return viewModel
});
