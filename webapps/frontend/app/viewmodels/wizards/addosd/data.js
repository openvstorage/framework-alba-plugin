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
define(['knockout', 'jquery',
    'ovs/generic', 'ovs/services/forms/form'],
    function(ko, $,
             generic, Form){
    "use strict";

    function Data(node, nodeCluster, slots, confirmOnly) {
        var self = this;

        var countDisplay = ['gather'];
        if (node.type() === 'ASD') {
            countDisplay = ['confirm']
        }
        var osdTypeItems;
        if (node.type() === 'S3') {
            osdTypeItems = ['S3']
        } else {
            osdTypeItems = ['ASD', 'AD']
        }
        var formMapping = {
            'ips': {
                'extender': {regex: generic.ipRegex},
                'displayOn': ['gather']
            },
            'port': {
                'extender': {numeric: {min: 1, max: 65535}},
                'group': 1,
                'displayOn': ['gather']
            },
            'osd_type': {
                'fieldMap': 'type',  // Translate osd_type to type so in the form it will be self.data.formdata().type
                'inputType': 'dropdown',  // Generate dropdown, needs items
                'inputItems': ko.observableArray(osdTypeItems),
                'inputTextFormatFunc': function(item) { return $.t('alba:generic.osdtypes.' + item.toLowerCase()); },
                'group': 2,
                'displayOn': ['gather']
            },
            'count': {
                'extender': {numeric: {min: 1, max: 24}},
                'group': 3,
                'displayOn': countDisplay
            },
            'buckets': {
                'displayOn': ['gather'],
                'group': 4
            }
        };

        self.node               = node;
        self.nodeCluster        = nodeCluster;
        self.slots              = slots;
        self.form               = new Form(ko.toJS(node.node_metadata), formMapping);
        self.confirmOnly        = ko.observable(confirmOnly);

        self.workingWithCluster = ko.pureComputed(function() {
            return !!self.nodeCluster
        })
    }
    return Data;
});
