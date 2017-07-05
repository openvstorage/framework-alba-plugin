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
    './data'
], function($, ko, api, shared, generic, data) {
    "use strict";
    return function() {
        var self = this;

        // Variables
        self.data = data;
        self.shared = shared;

        // Computed
        self.canContinue = ko.computed(function () {
            return {value: true, reasons: [], fields: []};
        });

        self.finish = function () {
            return $.Deferred(function (deferred) {
                // Add ALBA node
                if (self.data.oldNode() === undefined) {
                    generic.alertInfo(
                        $.t('alba:wizards.add_alba_node.confirm.started'),
                        $.t('alba:wizards.add_alba_node.confirm.in_progress')
                    );
                    deferred.resolve();
                    api.post('alba/nodes', {
                        data: {
                            node_id: self.data.newNode().nodeID(),
                            node_type: self.data.newNode().type()
                        }
                    })
                        .then(self.shared.tasks.wait)
                        .done(function () {
                            generic.alertSuccess(
                                $.t('alba:wizards.add_alba_node.confirm.complete'),
                                $.t('alba:wizards.add_alba_node.confirm.success')
                            );
                        })
                        .fail(function (error) {
                            error = generic.extractErrorMessage(error);
                            generic.alertError(
                                $.t('ovs:generic.error'),
                                $.t('alba:wizards.add_alba_node.confirm.failed', {why: error})
                            );
                        });
                // Replace ALBA node
                } else {
                    $.each(self.data.oldNode().disks(), function(index, disk) {
                        disk.processing(true);
                        $.each(disk.osds(), function(jndex, osd) {
                            osd.processing(true);
                        })
                    });
                    generic.alertInfo(
                        $.t('alba:wizards.replace_alba_node.started'),
                        $.t('alba:wizards.replace_alba_node.in_progress')
                    );
                    deferred.resolve();
                    api.post('alba/nodes/' + self.data.oldNode().guid() + '/replace_node', {data: {new_node_id: self.data.newNode().nodeID()}})
                        .then(self.shared.tasks.wait)
                        .done(function() {
                            generic.alertSuccess(
                                $.t('alba:wizards.replace_alba_node.complete'),
                                $.t('alba:wizards.replace_alba_node.success')
                            );
                        })
                        .fail(function (error) {
                            error = generic.extractErrorMessage(error);
                            generic.alertError(
                                $.t('ovs:generic.error'),
                                $.t('alba:wizards.replace_alba_node.failed', {why: error})
                            );
                        })
                        .always(function() {
                            $.each(self.data.oldNode().disks(), function(index, disk) {
                                disk.processing(false);
                                $.each(disk.osds(), function(jndex, osd) {
                                    osd.processing(false);
                                })
                            });
                        })
                }
            }).promise();
        };
    }
});
