# Copyright 2014 CloudFounders NV
# All rights reserved

"""
Kinetic extension
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
from kinetic.common import LogTypes
from kinetic.kinetic_pb2 import Message
from kinetic import AdminClient
from ovs.log.logHandler import LogHandler

logger = LogHandler('alba.extensions', name='kinetic')


class Kinetic(object):
    """
    Contains methods to control Kinetic devices directly
    """

    @staticmethod
    def discover(interval=0):
        """
        Discovers kinetic devices.
        @param interval: Multicast interval for the kinetic drives. <= 0 for autodetect. Use a fixed interval if possible (faster)
        @type interval: int

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
        """
        auto_interval = interval <= 0
        max_interval = 60  # We won't listen longer than X seconds

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
            key = None
            all_data = None
            network_interfaces = []
            for interface in data['network_interfaces']:
                if 'mac_addr' in interface and 'ipv4_addr' in interface and interface['ipv4_addr'] != '127.0.0.1':
                    # Below two lines are mainly for cleaning out invalid interfaces from a simulator running on an OVS node
                    if not Kinetic.is_valid(interface['ipv4_addr'], interface['mac_addr'], data['port']):
                        continue
                    if key is None:
                        all_data = Kinetic.get_device_info(interface['ipv4_addr'], data['port'])
                        key = all_data['configuration']['serialNumber'].lower()
                    network_interfaces.append({'ip_address': interface['ipv4_addr'],
                                               'mac_address': interface['mac_addr'],
                                               'interface': interface['name'],
                                               'port': data['port'],
                                               'tlsPort': data['tlsPort']})
            if not network_interfaces:
                continue
            result_data = {'network_interfaces': network_interfaces}
            dict_keys = ['utilization', 'temperature', 'capacity', 'configuration', 'statistics', 'limits']
            for dict_key in dict_keys:
                result_data[dict_key] = all_data[dict_key]
            if key not in results:
                timestamps[key] = time.time()
                results[key] = result_data
                if auto_interval and time.time() - start > max_interval:
                    break  # We stop after a certain amount of time anyway
            elif auto_interval:
                break

        return [results[key] for key in sorted(results.keys())]

    @staticmethod
    def get_device_info(ip, port):
        """
        Loads information about a Kinetic device
        """
        messagetypes = Message.MessageType.DESCRIPTOR.values_by_number
        logtypes = LogTypes.all()
        client = AdminClient(ip, port)
        client.connect()
        information = client.getLog(logtypes)
        client.close()
        interfaces = [i for i in information.configuration.interface
                      if hasattr(i, 'MAC') and i.ipv4Address != '127.0.0.1' and Kinetic.is_valid(i.ipv4Address, i.MAC)]
        return {'utilization': dict((u.name, u.value) for u in information.utilization),
                'temperature': dict((t.name, {'current': t.current,
                                              'minimum': t.minimum,
                                              'maximum': t.maximum,
                                              'target': t.target}) for t in information.temperature),
                'capacity': {'nominal': information.capacity.nominalCapacityInBytes,
                             'percent_empty': information.capacity.portionFull},
                'configuration': dict((p, getattr(information.configuration, p)) for p in dir(information.configuration)
                                      if p in ['model', 'protocolCompilationDate', 'protocolSourceHash',
                                               'protocolVersion', 'serialNumber', 'sourceHash', 'vendor',
                                               'version', 'worldWideName']),
                'statistics': dict((messagetypes[s.messageType].name, {'count': s.count,
                                                                       'bytes': s.bytes})
                                   for s in information.statistics),
                'limits': dict((l, getattr(information.limits, l)) for l in dir(information.limits)
                               if l in ['maxConnections', 'maxIdentityCount', 'maxKeyRangeCount', 'maxKeySize',
                                        'maxMessageSize', 'maxOutstandingReadRequests', 'maxOutstandingWriteRequests',
                                        'maxTagSize', 'maxValueSize', 'maxVersionSize']),
                'network_interfaces': [{'ip_address': i.ipv4Address,
                                        'mac_address': i.MAC,
                                        'interface': i.name,
                                        'port': information.configuration.port,
                                        'tlsPort': information.configuration.tlsPort} for i in interfaces]}

    @staticmethod
    def is_valid(ip, mac, port=None):
        """
        Checks if an ip/port is invalid (e.g. unreachable or a local ip with different mac)
        """
        local_ips = check_output('ip a', shell=True)
        for found_mac, found_ip in re.findall('link/ether ([a-f0-9]{2}:[a-f0-9]{2}:[a-f0-9]{2}:[a-f0-9]{2}:[a-f0-9]{2}:[a-f0-9]{2}).*?inet ([^/]+)/', local_ips, flags=re.S):
            if found_ip == ip and found_mac != mac:
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
