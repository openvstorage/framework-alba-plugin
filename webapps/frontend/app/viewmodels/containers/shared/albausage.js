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
    'ovs/generic',
    'viewmodels/containers/shared/base_container'
], function($, ko,
            generic,
            BaseContainer) {
    "use strict";
    var viewModelMapping = {};

    /**
     * AlbaUsage viewModel
     * @param data: Data to include in the model
     */
    function AlbaUsage(data) {
        var self = this;
        BaseContainer.call(self);

        // Constants

        var vmData = $.extend({
            size: null,
            used: null,
            available: null
        }, data);

        ko.mapping.fromJS(vmData, viewModelMapping, self);  // Bind the data into this

        // Computed
        self.usedBytes = ko.pureComputed(function() {
            return generic.formatBytes(self.used())
        });
        self.sizeBytes = ko.pureComputed(function() {
            return generic.formatBytes(self.size())
        });
        self.freeBytes = ko.pureComputed(function() {
            return generic.formatBytes(self.free())
        });
        self.usagePercentage = ko.pureComputed(function() {
            return generic.formatPercentage(self.used() / self.size(), true)
        });
        self.availablePercentage = ko.pureComputed(function() {
            return generic.formatPercentage(self.available() / self.size(), true)
        });
        self.displayUsage = ko.pureComputed(function() {
            return '{0} / {1}'.format(self.usedBytes(), self.sizeBytes())
        });
    }
    // Prototypical inheritance
    AlbaUsage.prototype = $.extend({}, BaseContainer.prototype);
    return AlbaUsage
});
