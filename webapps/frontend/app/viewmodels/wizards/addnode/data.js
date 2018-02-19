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
define(['knockout',
        'ovs/generic'],
    function(ko, generic){
    "use strict";
    function viewModel(newNode, oldNode, confirmOnly) {
        var self = this;
        var typeEnum = Object.freeze({generic: 'GENERIC', cluster: 'ALBANODECLUSTER'});
        // Observables
        self.name = ko.observable('').extend({regex: generic.nameRegex});
        self.newNode = ko.observable(newNode);
        self.oldNode = ko.observable(oldNode);
        self.nodeTypes = ko.observableArray(Object.values(typeEnum));
        self.confirmOnly = ko.observable(confirmOnly || false);

        // Computed
        self.willIDBeGenerated = ko.pureComputed(function() {
            // The item is a always an empty AlbaNode when adding it. The type of it can be changed at will but when it is
            // 'ASDNODECLUSTER' we need to make sure the right api is called and the ID won't be generated
            return self.newNode().nodeID() === undefined && !self.workingWithCluster()
        });
        self.workingWithCluster = ko.pureComputed(function() {
            return self.newNode().type() === typeEnum.cluster
        });
        self.displayConnectionDetail = ko.pureComputed(function(){
           return !Object.values(typeEnum).contains(self.newNode().type())
        })
    }
    return viewModel;
});
