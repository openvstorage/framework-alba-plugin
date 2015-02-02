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

cat <<EOF > /opt/alba/arakoon/cfg/alba.ini
[global]
cluster =  arakoon_0
cluster_id = alba

plugins = albamgr_plugin nsm_host_plugin

[arakoon_0]
ip = 127.0.0.1
client_port = 4000
messaging_port = 4010
home = /opt/alba/arakoon
log_level = debug
EOF

PKG=$1

# stop asds
echo
stop alba-proxy
stop alba-arakoon
echo

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

cat <<EOF > /etc/init/alba-proxy.conf
description "alba proxy"

start on (local-filesystems and started networking)
stop on runlevel [016]

kill timeout 60
respawn
respawn limit 10 5
console log
setuid root
setgid root

env LD_LIBRARY_PATH=/opt/alba/lib
chdir /opt/alba/

exec /opt/alba/bin/alba proxy-start --config /opt/alba/arakoon/cfg/alba.ini
EOF

cat << EOF > /etc/init/alba-arakoon.conf
description "alba arakoon"

start on (local-filesystems and started networking)
stop on runlevel [016]

kill timeout 60
respawn
respawn limit 10 5
console log
setuid root
setgid root

env LD_LIBRARY_PATH=/opt/alba/lib
chdir /opt/alba/arakoon

exec /opt/alba/arakoon/bin/alba-arakoon --node arakoon_0 -config /opt/alba/arakoon/cfg/alba.ini
EOF

export LD_LIBRARY_PATH=/opt/alba/lib

echo
start alba-arakoon
sleep 1

# nsm host registration
# /opt/alba/bin/alba add-nsm-host --config /opt/alba/arakoon/cfg/alba.ini /opt/alba/arakoon/cfg/alba.ini

start alba-proxy

echo
echo "Alba manager/proxy updated to version: ${PKG}"
echo "Status:"
status alba-arakoon
status alba-proxy
echo

tail /var/log/upstart/alba-arakoon.log
tail /var/log/upstart/alba-proxy.log

ps -ef | grep alba