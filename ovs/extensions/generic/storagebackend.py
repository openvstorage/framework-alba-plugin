# Copyright 2014 CloudFounders NV
# All rights reserved

"""
Storage backend extension
"""

import time
import socket
import struct
import re
import fcntl
import os
import errno
import json
from subprocess import check_output


class Storagebackend(object):
    """
    Contains methods to control storage backend devices
    """

    @staticmethod
    def discover(interval=0, connect=False):
        """
        Discovers generic storage backend devices.
        @param interval: Multicast interval <= 0 for autodetect. Use a fixed interval if possible (faster)
        @type interval: int

        @param connect: connect to device during discovery process
        @type connect: boolean

        Example data format from a physical Kinetic drive:
        {'tlsPort': 8443,
         'port': 8123,
         'network_interfaces': [{'ipv6_addr': 'fe80::20c:50ff:fe06:f31c',
                                 'ipv4_addr': '192.168.11.145',
                                 'mac_addr': '00:0c:50:06:f3:1c',
                                 'name': 'eth0'},
                                {'ipv6_addr': 'fe80::20c:50ff:fe06:f31d',
                                 'ipv4_addr': '192.168.11.149',
                                 'mac_addr': '00:0c:50:06:f3:1d',
                                 'name': 'eth1'}]}

        Example alba multicast info:
        {u'box_id': u'1', u'network_interfaces': [{u'ipv4_addr': u'10.100.186.211'}], u'used_bytes': u'80760832',
         u'port': 8004, u'version': u'AsdV1', u'total_bytes': u'1868837576704',
         u'id': u'0291bf82-561a-4954-a7b3-60ec7f2a1094'}

        Example seagate kinetic multicast info
        {"firmware_version":"2.2.4","manufacturer":"Seagate","model":"ST4000NC000-1FR168",
         "network_interfaces":[{"ipv4_addr":"192.168.11.136",
                                "ipv6_addr":"fe80::20c:50ff:fe06:eeea",
                                "mac_addr":"00:0c:50:06:ee:ea",
                                "name":"eth0"},
                               {"ipv4_addr":"192.168.11.129",
                                "ipv6_addr":"fe80::20c:50ff:fe06:eeeb",
                                "mac_addr":"00:0c:50:06:ee:eb",
                                "name":"eth1"}],
                                "port":8123,"protocol_version":"3.0.0",
                                "serial_number":"Z30087D7",
                                "tlsPort":8443,
                                "world_wide_name":"5 000c50 05002c1ff"}
        """
        auto_interval = interval <= 0
        max_interval = 10  # We won't listen longer than X seconds

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', 8123))

        mreq = struct.pack('=4sl', socket.inet_aton('239.1.2.3'), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        fcntl.fcntl(sock, fcntl.F_SETFL, os.O_NONBLOCK)  # Use this instead of the socket.<whatever>() methods

        results = {}
        timestamps = {}
        start = time.time()
        while True:
            if not auto_interval and time.time() - start > (interval + 1):
                break
            try:
                data = sock.recv(10240)
            except socket.error, e:
                err = e.args[0]
                if err == errno.EAGAIN or err == errno.EWOULDBLOCK:
                    # No data available
                    time.sleep(1)
                    continue
                else:
                    # Socket closed or whatever "generic" error.
                    return {}
            data = json.loads(data)
            network_interfaces = []

            result_data = {'utilization': 'NA',
                           'temperature': 'NA',
                           'capacity': {'nominal': 0},
                           'configuration': {},
                           'statistics': 'NA',
                           'limits': 'NA',
                           'information': {}
                           }

            # determine type
            if 'id' in data:
                # asd
                key = data['id'].lower()
                result_data['capacity']['nominal'] = data['total_bytes']
                result_data['configuration']['chassis'] = data['box_id']
                result_data['configuration']['model'] = data['version']
                result_data['configuration']['serialNumber'] = key
                result_data['configuration']['type'] = 'ASD'
                result_data['information']['used_bytes'] = data['used_bytes']
                result_data['information']['total_bytes'] = data['total_bytes']
                result_data['serialNumber'] = key

            elif 'serial_number' in data:
                # kinetic
                key = data['serial_number'].lower()
                result_data['configuration']['chassis'] = 'NA'
                result_data['configuration']['model'] = data['model']
                result_data['configuration']['serialNumber'] = key
                result_data['configuration']['tlsPort'] = 'tlsPort'
                result_data['configuration']['type'] = 'KINETIC'
                result_data['information']['firmware_version'] = data['firmware_version']
                result_data['information']['manufacturer'] = data['manufacturer']
                result_data['information']['protocol_version'] = data['protocol_version']
                result_data['information']['world_wide_name'] = data['world_wide_name']
                result_data['serialNumber'] = key

            for interface in data['network_interfaces']:
                if 'ipv4_addr' in interface and interface['ipv4_addr'] != '127.0.0.1':
                    # @todo: only add reachable ip's ?
                    network_interfaces.append({'ip_address': interface['ipv4_addr'],
                                               'port': data['port']})
            if not network_interfaces:
                continue

            result_data['network_interfaces'] = network_interfaces

            if key not in results:
                timestamps[key] = time.time()
                results[key] = result_data
                if auto_interval and time.time() - start > max_interval:
                    break  # We stop after a certain amount of time anyway
            elif auto_interval:
                break

        return [results[key] for key in sorted(results.keys())]

    @staticmethod
    def is_valid(ip, port=None):
        """
        Checks if an ip/port is invalid (e.g. unreachable or a local ip with different mac)
        """
        local_ips = check_output('ip a', shell=True)
        for found_mac, found_ip in re.findall('link/ether ([a-f0-9]{2}:[a-f0-9]{2}:[a-f0-9]{2}:[a-f0-9]{2}:[a-f0-9]{2}:[a-f0-9]{2}).*?inet ([^/]+)/', local_ips, flags=re.S):
            if found_ip == ip:
                return False
        if port is not None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            try:
                sock.connect((ip, port))
                sock.close()
            except Exception:
                return False
        return True
