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
    'viewmodels/services/albanode', 'viewmodels/services/albanodecluster'
], function($, ko,
            api, shared, generic,
            albaNodeService, albaNodeClusterService) {
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

        // Function
        self.gatherSlotData = function() {
            // Gather info from the dynamic form
            var slotData = [];
            $.each(self.data.slots, function(_, slot) {
                var osdData = {
                    slot_id: slot.slot_id(),
                    alba_backend_guid: self.data.node.albaBackend.guid()
                };
                $.extend(osdData, self.data.form.gatherData());
                // @TODO remove this part as type should be fetched
                if (!('osd_type' in osdData)) {
                    osdData.osd_type = 'ASD';
                }
                slotData.push(osdData);
            });
            return slotData;
        };
        self.finish = function () {
            var slotData = self.gatherSlotData();
            var node = self.data.node;
            var nodeCluster = self.data.nodeCluster;
            var osdAmount = slotData[0].hasOwnProperty('count') ? slotData[0].count : 1;
            var slotAmount = slotData.length;
            if (slotAmount === 1) {
                generic.alertInfo(
                    $.t('alba:wizards.add_osd.confirm.started'),
                    $.t('alba:wizards.add_osd.confirm.started_msg', {
                        name: slotData[0].slot_id,
                        multi: osdAmount > 1 ? 's' : '',
                        amount: osdAmount
                    })
                );
            } else {
                generic.alertInfo(
                    $.t('alba:wizards.add_osd.confirm.started'),
                    $.t('alba:wizards.add_osd.confirm.started_multi_msg', {
                        multi: osdAmount > 1 ? 's' : '',
                        amount: osdAmount
                    })
                );
            }
            return $.when()  // Start a chain
                .then(function() {
                    return albaNodeService.fillSlots(node.guid(), slotData)
                })
                .then(function () {
                    if (slotAmount === 1) {
                        generic.alertSuccess(
                            $.t('alba:wizards.add_osd.confirm.success'),
                            $.t('alba:wizards.add_osd.confirm.success_msg', {
                                name: slotData[0].slot_id,
                                multi: osdAmount > 1 ? 's': '',
                                amount: osdAmount
                            })
                        );
                    } else {
                        generic.alertSuccess(
                            $.t('alba:wizards.add_osd.confirm.success'),
                            $.t('alba:wizards.add_osd.confirm.success_multi_msg', {
                                multi: osdAmount > 1 ? 's': '',
                                amount: osdAmount
                            })
                        );
                    }
                }, function(error) {
                    error = generic.extractErrorMessage(error);
                    if (slotAmount === 1) {
                        generic.alertError(
                            $.t('alba:wizards.add_osd.confirm.failure'),
                            $.t('alba:wizards.add_osd.confirm.failure_msg', {
                                why: error,
                                name: slotData[0].slot_id,
                                multi: osdAmount > 1 ? 's': '',
                                amount: osdAmount
                            })
                        );
                    } else {
                        generic.alertError(
                            $.t('alba:wizards.add_osd.confirm.failure'),
                            $.t('alba:wizards.add_osd.confirm.failure_multi_msg', {
                                why: error,
                                multi: osdAmount > 1 ? 's': '',
                                amount: osdAmount
                            })
                        );
                    }
                });
        };
    }
});
