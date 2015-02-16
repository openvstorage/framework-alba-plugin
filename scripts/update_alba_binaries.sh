#!/bin/bash

if [ -z "$1" ]
  then
    echo "Specify only 1 argument specifying alba pkg version to update to"
    echo "E.g. alba-b79a413"
    exit 1
fi

mkdir -p /opt/alba/bin
mkdir -p /opt/alba/arakoon/bin
mkdir -p /opt/alba/arakoon/cfg
mkdir -p /opt/alba/lib
mkdir -p /opt/alba/plugins

ln -s /opt/alba/plugins/albamgr_plugin.cmxs /opt/alba/arakoon/albamgr_plugin.cmxs
ln -s /opt/alba/plugins/nsm_host_plugin.cmxs /opt/alba/arakoon/nsm_host_plugin.cmxs

PKG=$1

# cleanup
rm /root/${PKG}.tgz
rm -rf /root/${PKG}

wget http://jenkins.cloudfounders.com/view/alba/job/alba_package/lastSuccessfulBuild/artifact/${PKG}.tgz
gunzip ${PKG}.tgz
tar xvf ${PKG}.tar
cd ${PKG}
cp bin/alba.native /opt/alba/bin/alba
cp bin/arakoon.native /opt/alba/arakoon/bin/alba-arakoon

cp plugins/* /opt/alba/plugins/

cp shared_libs/* /opt/alba/lib/

chmod 755 /opt/alba/bin/*
chmod 755 /opt/alba/arakoon/bin/*

echo
echo "Alba manager/proxy updated to version: ${PKG}"
echo "Status:"