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
    'viewmodels/services/albanodeservice', 'viewmodels/services/albanodeclusterservice'
], function($, ko, api, shared, generic, albaNodeService, albaNodeClusterService) {
    "use strict";
    return function(stepOptions) {
        var self = this;

        // Variables
        self.data   = stepOptions.data;
        self.shared = shared;

        // Computed
        self.canContinue = ko.computed(function () {
            return {value: true, reasons: [], fields: []};
        });

        // Functions
        function _handleMessaging(prefix, api) {
            generic.alertInfo($.t(prefix +'.started'), $.t(prefix + '.in_progress'));
            // Further data is present in args. This is JS-style *args
            var args = Array.prototype.slice.call(arguments, _handleMessaging.length);
            return api.apply(null, args)
                .then(self.shared.tasks.wait)
                .done(function () {
                    generic.alertSuccess(
                        $.t(prefix + '.complete'),
                        $.t(prefix + '.success')
                    );
                })
                .fail(function (error) {
                    error = generic.extractErrorMessage(error);
                    generic.alertError(
                        $.t('ovs:generic.error'),
                        $.t(prefix + '.failed', {
                            why: error
                        })
                    );
                });
        }
        function addNode() {
            var data = {
                node_id: self.data.newNode().nodeID(),
                node_type: self.data.newNode().type(),
                name: self.data.name()
            };
            return _handleMessaging('alba:wizards.add_node.confirm', albaNodeService.addAlbaNode, data)
        }
        function replaceNode() {
            $.each(self.data.oldNode().slots(), function(index, slot) {
                slot.processing(true);
                $.each(slot.osds(), function(jndex, osd) {
                    osd.processing(true);
                })
            });
            return _handleMessaging('alba:wizards.replace_node', albaNodeService.replaceAlbaNode, self.data.oldNode().guid(), self.data.newNode().nodeID())
                .always(function() {
                    $.each(self.data.oldNode().slots(), function(index, slot) {
                        slot.processing(false);
                        $.each(slot.osds(), function(jndex, osd) {
                            osd.processing(false);
                        })
                    });
                })
        }
        function addNodecluster() {
            var data = {name: self.data.name()};
            return _handleMessaging('alba:wizards.add_nodecluster', albaNodeClusterService.addAlbaNodeCluster, data)
        }
        self.finish = function () {
            // Add ALBA node
            if (self.data.workingWithCluster()) {
                return addNodecluster()
            }
            if (self.data.oldNode() === undefined) {
                return addNode()
            // Replace ALBA node
            } else {
                return replaceNode()
            }
        };
    }
});
