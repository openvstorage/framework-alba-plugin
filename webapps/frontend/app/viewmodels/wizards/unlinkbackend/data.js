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
define(['knockout'], function(ko){
    "use strict";
    var singleton = function() {
        var data = {
            confirmed:     ko.observable(false),
            linkedOSDInfo: ko.observable(),
            loaded:        ko.observable(false),
            safety:        ko.observable({}),
            target:        ko.observable()
        };
        data.shouldConfirm = ko.computed(function() {
            return (data.safety().lost !== undefined && data.safety().lost > 0) ||
                   (data.safety().critical !== undefined && data.safety().critical > 0);
        });
        return data;
    };
    return singleton();
});
