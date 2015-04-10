// Copyright 2014 CloudFounders NV
// All rights reserved
/*global define, require */
define(['jquery'], function($) {
    "use strict";
    return {
        routes: [
            { route: 'ovs-backend/:guid', moduleId: 'backend-alba-detail', title: $.t('alba:detail.title'), titlecode: 'alba:detail.title', nav: false, main: false }
        ],
        routePatches: [],
        dashboards: [
            'dashboard-alba'
        ]
    };
});
