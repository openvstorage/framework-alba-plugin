#!/bin/bash

if [ -z "$1" ]
  then
    echo "Specify only 1 argument specifying alba pkg version to update to"
    echo "E.g. alba-b79a413"
    exit 1
fi

mkdir -p /opt/alba/bin
mkdir -p /opt/alba/lib

PKG=$1

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

wget http://jenkins.cloudfounders.com/view/alba/job/alba_package/lastSuccessfulBuild/artifact/${PKG}.tgz
gunzip ${PKG}.tgz
tar xvf ${PKG}.tar
cd ${PKG}
cp bin/alba.native /opt/alba/bin/alba

cp shared_libs/libcrypto.so.1.0.0 /opt/alba/lib/
cp shared_libs/libssl.so.1.0.0 /opt/alba/lib/
cp shared_libs/libpthread.so.0 /opt/alba/lib/
cp shared_libs/libffi.so.6 /opt/alba/lib/
cp shared_libs/libstdc++.so.6 /opt/alba/lib/
cp shared_libs/libsnappy.so.1 /opt/alba/lib/
cp shared_libs/libbz2.so.1.0 /opt/alba/lib/
cp shared_libs/libz.so.1 /opt/alba/lib/
cp shared_libs/librocksdb.so /opt/alba/lib/
cp shared_libs/libJerasure.so.2 /opt/alba/lib/
cp shared_libs/libm.so.6 /opt/alba/lib/
cp shared_libs/libdl.so.2 /opt/alba/lib/
cp shared_libs/libgcc_s.so.1 /opt/alba/lib/
cp shared_libs/libc.so.6 /opt/alba/lib/
cp shared_libs/libgf_complete.so.1 /opt/alba/lib

chmod 755 /opt/alba/bin/*

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
