#!/bin/bash

if [ -z "$1" -o "$1" = "-h" ]; then
  echo "command: <PKG> [-clean]"
  echo "e.g.:"
  echo "Update alba binaries and keep data + configuration: "
  echo "./update_alba.sh alba-0.1.0-467-gd939655"
  echo ""
  echo "Update and clean database/asd id:"
  echo "./update_alba.sh alba-0.1.0-467-gd939655 -clean"
  echo ""
  exit 0
fi

mkdir -p /opt/alba/bin
mkdir -p /opt/alba/lib

PKG=$1
BOX_ID=1

# status asds
echo
echo "Status:"
status alba-data1
status alba-data2
status alba-data3
status alba-data4

# stop asds
echo
stop alba-data1
stop alba-data2
stop alba-data3
stop alba-data4
echo

# cleanup
rm /root/${PKG}.tgz
rm -rf /root/${PKG}

if [ "$2" = "-clean" ]; then
    rm -rf /mnt/data*/*
fi

wget http://jenkins.cloudfounders.com/view/alba/job/alba_package/lastSuccessfulBuild/artifact/${PKG}.tgz
gunzip ${PKG}.tgz
tar xvf ${PKG}.tar
cd ${PKG}
cp bin/alba.native /opt/alba/bin/alba

cp shared_libs/* /opt/alba/lib/

chmod 755 /opt/alba/bin/*

port=8000
for asd in data1 data2 data3 data4; do
  (( port = port + 1))
  if [ "$2" = "-clean" -o ! -f "/etc/init/alba-${asd}.conf" ]; then
  cat <<EOF > /etc/init/alba-${asd}.conf
description "alba osd startup"

start on (local-filesystems and started networking)
stop on runlevel [016]

kill timeout 60
respawn
respawn limit 10 5
console log
setuid alba
setgid alba

env LD_LIBRARY_PATH=/opt/alba/lib
chdir /opt/alba

exec /opt/alba/bin/alba asd-start --path /mnt/${asd} --host 10.100.186.211 --port ${port} --box-id ${BOX_ID}
EOF
  fi
done

echo
start alba-data1
start alba-data2
start alba-data3
start alba-data4

echo
echo "Alba ASDs updated to version: ${PKG}"
echo "Status:"
status alba-data1
status alba-data2
status alba-data3
status alba-data4
echo

tail /var/log/upstart/alba-data1.log
tail /var/log/upstart/alba-data2.log
tail /var/log/upstart/alba-data3.log
tail /var/log/upstart/alba-data4.log

ps -ef | grep alba