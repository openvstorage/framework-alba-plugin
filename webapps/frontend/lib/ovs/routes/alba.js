// Copyright 2014 CloudFounders NV
// All rights reserved
/*global define, require */
define(['jquery'], function($) {
    "use strict";
    return {
        routes: [
            { route: 'backend-alba/:guid',     moduleId: 'backend-alba-detail',     title: $.t('alba:detail.title'),      titlecode: 'alba:detail.title',      nav: false, main: false },
            { route: 'alba-livekinetic/:guid', moduleId: 'alba-livekinetic-detail', title: $.t('alba:livekinetic.title'), titlecode: 'alba:livekinetic.title', nav: false, main: false }
        ]
    };
});
