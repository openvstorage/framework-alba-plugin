// Copyright 2015 CloudFounders NV
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
define(['knockout'], function(ko){
    "use strict";
    var singleton = function() {
        var data = {
            safety: ko.observable({}),
            confirmed:  ko.observable(false),
            loaded: ko.observable(false),
            albaOSD: ko.observable(),
            albaBackend: ko.observable(),
            albaNode: ko.observable()
        };
        data.shouldConfirm = ko.computed(function() {
            return (data.safety().lost !== undefined && data.safety().lost > 0) ||
                   (data.safety().critical !== undefined && data.safety().critical > 0);
        });
        return data;
    };
    return singleton();
});
