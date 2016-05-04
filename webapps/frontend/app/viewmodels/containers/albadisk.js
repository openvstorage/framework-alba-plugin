// Copyright 2016 iNuron NV
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
/*global define */
define([
    'jquery', 'knockout', 'ovs/generic',
    './albaosd'
], function($, ko, generic, OSD) {
    "use strict";
    return function(name) {
        var self = this;

        // External injected
        self.node = undefined;

        // Observables
        self.ignoreNext   = ko.observable(false);
        self.loaded       = ko.observable(false);
        self.guid         = ko.observable();
        self.name         = ko.observable(name);
        self.nodeID       = ko.observable();
        self.asds         = ko.observableArray([]);
        self.usage        = ko.observable();
        self.status       = ko.observable();
        self.statusDetail = ko.observable();
        self.device       = ko.observable();
        self.mountpoint   = ko.observable();
        self.processing   = ko.observable(false);
        self.highlighted  = ko.observable(false);

        // Computed
        self.canRemove = ko.computed(function() {
            var onlyAvailable = true;
            $.each(self.asds(), function(index, asd) {
                if (asd.status() !== 'available') {
                    onlyAvailable = false;
                    return false;
                }
            });
            return onlyAvailable;
        });
        self.canClaim = ko.computed(function() {
            var hasAvailable = false;
            $.each(self.asds(), function(index, asd) {
                if (asd.status() === 'available') {
                    hasAvailable = true;
                    return false;
                }
            });
            return hasAvailable;
        });
        self.locked = ko.computed(function() {
            return ['nodedown', 'unknown'].contains(self.statusDetail());
        });

        // Functions
        self.fillData = function(data) {
            if (self.ignoreNext() === true) {
                self.ignoreNext(false);
            } else {
                self.status(data.status);
                self.nodeID(data.node_id);
                generic.trySet(self.guid, data, 'guid');
                generic.trySet(self.statusDetail, data, 'status_detail');
                generic.trySet(self.usage, data, 'usage');
                generic.trySet(self.device, data, 'device');
                generic.trySet(self.mountpoint, data, 'mountpoint');

                if (!data.hasOwnProperty('asds')) {
                    return;
                }
                var asdIDs = [], asds = {};
                $.each(data.asds, function (index, asd) {
                    asdIDs.push(asd.asd_id);
                    asds[asd.asd_id] = asd;
                });
                generic.crossFiller(
                    asdIDs, self.asds,
                    function (id) {
                        var osd = new OSD(id);
                        osd.disk = self;
                        return osd;
                    }, 'asdID'
                );
                $.each(self.asds(), function (index, asd) {
                    if ($.inArray(asd.asdID(), asdIDs) !== -1) {
                        asd.fillData(asds[asd.asdID()]);
                    }
                });
                self.asds.sort(function (a, b) {
                    return a.asdID() < b.asdID() ? -1 : 1;
                });
            }

            self.loaded(true);
        };

        self.initialize = function() {
            return self.node.initializeDisk(self);
        };
        self.remove = function() {
            return self.node.removeDisk(self);
        };
        self.restart = function() {
            return self.node.restartDisk(self);
        };
        self.claimOSDs = function() {
            var asds = {};
            asds[self.guid()] = [];
            $.each(self.asds(), function (index, asd) {
                if (asd.status() === 'available') {
                    asds[self.guid()].push(asd);
                }
            });
            return self.node.claimOSDs(asds);
        };
    };
});
