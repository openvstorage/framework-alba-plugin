#!/bin/bash

if [ -z "$1" -o "$1" = "-h" -o "$1" = "-clean" ]; then
  echo "command: <BOX_ID> [-clean]"
  echo "script uses 4 mountpoints:"
  echo "/mnt/data1 through /mnt/data4"
  echo "these could be directories or actual mountpoints on sata / ssd devices as preferred"
  echo ""
  echo "Note when changing the box_id -clean option is mandatory"
  echo "e.g.:"
  echo "Update alba binaries, use box_id 1 and preserve data:"
  echo "./update_alba.sh 1"
  echo ""
  echo "Update alba binaries, use box_id 1 and cleanup data:"
  echo "./update_alba.sh 1 -clean"
  echo ""
  exit 0
fi
MY_IP=`cat /etc/hosts | grep \`hostname\` | awk '{print $1}'`
BOX_ID=$1

# create user if necessary
id alba
if [ $? -eq 1 ]; then
    useradd -b /home -d /home/alba -m alba
fi

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

echo "deb http://packages.cloudfounders.com/apt/ unstable/" > /etc/apt/sources.list.d/ovsaptrepo.list
apt-get update
apt-get install --force-yes --yes alba

if [ "$2" = "-clean" ]; then
    rm -rf /mnt/data*/*
fi

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

env LD_LIBRARY_PATH=/usr/lib/alba

pre-start script
    # create json config file
    cat << E2OF > /home/alba/${asd}.json
{"home": "/mnt/${asd}", "box_id": "${BOX_ID}", "log_level": "debug", "port": ${port}, "ips": ["${MY_IP}"] }

E2OF

end script

exec /usr/bin/alba asd-start --config /home/alba/${asd}.json
EOF
  fi
done

echo
start alba-data1
start alba-data2
start alba-data3
start alba-data4

echo
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
echo "Alba version:"
/usr/bin/alba version