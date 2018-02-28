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
    'viewmodels/services/albanodeclusterservice'
], function($, ko, api, shared, generic, albaNodeClusterService) {
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
        self.finish = function () {
            generic.alertInfo($.t('alba:wizards.register_node_under_cluster.confirm.started'), $.t('alba:wizards.register_node_under_cluster.confirm.in_progress'));
            var albaNodeIDs = self.data.selectedAlbaNodes().map(function(albaNode) {
                return albaNode.node_id()
            });
            return albaNodeClusterService.registerAlbaNodes(self.data.albaNodeCluster.guid(), albaNodeIDs)
                .then(self.shared.tasks.wait)
                .then(function (data) {
                    generic.alertSuccess(
                        $.t('alba:wizards.register_node_under_cluster.confirm.complete'),
                        $.t('alba:wizards.register_node_under_cluster.confirm.success'));
                    return data;
                }, function (error) {
                    error = generic.extractErrorMessage(error);
                    generic.alertError(
                        $.t('ovs:generic.error'),
                        $.t('alba:wizards.register_node_under_cluster.confirm.failed', {
                            why: error
                        }));
                    return error;
                })
        };
    }
});
