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
    'viewmodels/containers/shared/base_container', 'viewmodels/containers/backend/albabackend', 'viewmodels/containers/shared/albausage',
    'viewmodels/services/subscriber'
], function(app, ko, $,
            generic,
            BaseContainer, AlbaBackend, AlbaUsage,
            subscriberService) {
    "use strict";

    var viewModelMapping = {
        alba_backend: {
            key: function (data) {  // For relation updates: check if the GUID has changed before discarding a model
                return ko.utils.unwrapObservable(data.guid)
            },
            create: function (options) {
                return new AlbaBackend(ko.utils.unwrapObservable(options.parent.alba_backend_guid) || null);
            }
        },
        'usage': {
            create: function(options){
                return new AlbaUsage(options.data)
            }
        }
    };
    var albaBackendDetailContext = 'albaBackendDetail';
    /**
     * AlbaOSD viewModel
     * @param data: Data about the model (see vmData for layout). Similar to the data retrieved from the API
     */
    function AlbaOSD(data) {
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
            ok: 'ok',
            unknown: 'unknown',
            uninitialized: 'uninitialized'
        }, self.errorStatuses));

        self.statusDetails = Object.freeze({
            null: null,
            ownership_query_fail: 'ownership_query_fail'
        });

        // Observables
        self._status =          ko.observable();
        self._status_detail =   ko.observable();
        self.loaded =           ko.observable(false);
        self.processing =       ko.observable(false);

        var vmData = $.extend({
            alba_backend: {},
            alba_backend_guid: null,  // Guid of the AlbaBackend of the AlbaDetailView
            claimed_by: null,
            slot_id: null,
            guid: null,
            osd_id: null,
            usage: {size: null, used: null, available: null},
            device: null,
            mountpount: null,
            port: null,
            ips: [],
            type: null,
            status: null,  // One of the self.statusses options
            node_id: null,
            node_metadata: {} // Can be both an object with properties or a viewModel with observable
        }, data);

        ko.mapping.fromJS(vmData, viewModelMapping, self);  // Bind the data into this
        self.getBackend();
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
        self.status_detail = ko.computed({
            deferEvaluation: true,  // Wait with computing for an actual subscription
            read: function() {
                if (self._status() === self.statusses.ok && self._status_detail() === null) {
                    return self.statusDetails.ownership_query_fail
                }
                return self._status_detail()
            },
            write: function(statusDetail) {
                self._status_detail(statusDetail)
            }
        });
        self.hasErrorStatus = ko.pureComputed(function() {
            return Object.values(self.errorStatuses).contains(self.status()) && self.status_detail() !== undefined && self.status_detail() !== ''
        });
        self.isLocal = ko.pureComputed(function() {
            return [null, undefined].contains(self.claimed_by()) || self.alba_backend_guid() === self.claimed_by();
        });
        self.locked = ko.pureComputed(function() {
            return [self.statusses.nodedown, self.statusses.unknown].contains(self.status_detail()) || !self.isLocal();
        });
        self.marked = ko.pureComputed(function() {
            return (self.status() === self.errorStatuses.unavailable || (!self.isLocal() && (self.status() === self.errorStatuses.warning || self.status() === self.errorStatuses.error)))
                && self.alba_backend.loaded();
        });
        self.sockets = ko.pureComputed(function() {
            var sockets = [];
            $.each(self.ips(), function(index, ip) {
               sockets.push(ip + ":" + self.port())
            });
            return sockets
        });
        self.displayUsage = ko.pureComputed(function() {
            return ![self.statusses.unavailable, self.statusses.uninitialized].contains(self.status) && ko.utils.unwrapObservable(self.usage.used)
        });

        // Events - albaBackendDetail
        self.claim = function() {
            var data = {};
            data[self.slot_id()] = {osds: [self]};
            subscriberService.trigger('albanode_{0}:claim_osds'.format(self.node_id()), data);
        };
        self.remove = function() {
            subscriberService.trigger('albanode_{0}:remove_osd'.format(self.node_id()), self);
        };
        self.restart = function() {
            subscriberService.trigger('albanode_{0}:restart_osd'.format(self.node_id()), self);
        };
    }
    // Prototypical inheritance
    var functions = {
        /**
         * Retrieves the AlbaBackendData from the AlbaBackendDetail viewModel/controller
         * @return {Promise}
         */
        getBackend: function() {
            var self = this;
            return $.when()
                .then(function(){
                    if (!self.alba_backend_guid()) {
                        return null
                    }
                    var responseEvent = 'osd_{0}:load_alba_backend'.format(self.osd_id());
                    var data = {
                        response: responseEvent,
                        albaBackendGuid: self.alba_backend_guid()
                    };
                    var subscription = subscriberService.onEvents(responseEvent, albaBackendDetailContext).then(function(data){
                        self.alba_backend.update(data);
                        return data
                    });
                    subscriberService.trigger('alba_backend:load', data); // Trigger the ask
                    return subscription
                });
        }
    };
    AlbaOSD.prototype = $.extend({}, BaseContainer.prototype, functions);
    return AlbaOSD
});
