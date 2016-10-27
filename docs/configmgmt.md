## Configuration Management

As Open vStorage is completely distributed it uses a distributed configuration management system.
There are 2 option as configuration management system:
* Arakoon, the preferred and advised system.
* ETCD

### Set, get and list configuration keys
The [OVS commandline](https://openvstorage.gitbooks.io/administration/content/Administration/usingthecli/configmgmt.html) allows to easily list and change the configuration parameters of the cluster:
* `ovs config edit some/key`: Edit that key in your `$EDITOR`. If it doesn't exist, the key is created.
* `ovs config list some`: List all keys with the given prefix.
* `ovs config get some/key`: Print the content of the given key.


#### ALBA

##### Specific ASD node related keys
```
/ovs/alba/asdnodes/<node_id>/config/main = {"username": "root",
                                            "version": 0,
                                            "ip": "$Public IP of the ASD node",
                                            "node_id": "$Node ID for this ASD node, generated during 'asd-manager setup'",
                                            "password": "$Password for this ASD node, generated during 'asd-manager setup'",
                                            "port": 8500}
/ovs/alba/asdnodes/<node_id>/config/network = {"ips": [],  (Defaults to empty list, which means all IPs)
                                               "port": 8600}
```

##### Specific ASD related keys
```
/ovs/alba/asds/<asd_id>/config = {"asd_id": "$ASD ID generated during initialization of the disk",
                                  "node_id": "$Node ID to which ASD node this ASD is connected to",
                                  "capacity": $Size of the ASD in bytes,
                                  "home": "$Mountpoint of the ASD",  (E.g. /mnt/alba-asd/yaEIdD1lypngS3xE/CiUd8JkNGUHaCFH1ekUcUGkeGhc8JVJN)
                                  "log_level": "info",
                                  "rocksdb_block_cache_size": 488139647,
                                  "port": 8601,
                                  "transport": "tcp"}  (Transport can be 'tcp' or 'rdma')

```

##### Global Backend related keys
```
/ovs/alba/backends/default_nsm_hosts = "$Default amount of NSM hosts"  (Defaults to 1)
/ovs/alba/backends/global_gui_error_interval = "$ASDs are reported as warning/error for x seconds since last read/write failure"  (Defaults to 300)
```

##### Specific Backend related keys
```
/ovs/alba/backends/<guid>/maintenance/config = {"albamgr_cfg_url": "<some_path_to>/ovs/arakoon/<backend-name>-abm/config",
                                                "log_level": "info"}
/ovs/alba/backends/<guid>/maintenance/nr_of_agents = "$Amount of maintenance agents deployed for this backend"  (Defaults to amount of ALBA nodes)
```

### Changing the schedule for the ALBA backend verifictaion process
In case you want to change the schedule for the ALBA backend verifictaion process which checks the state of each object in the backend, add `"alba.scheduled.verify_namespaces": {"minute": "0", "hour": "0", "month_of_year": "*/X"}` to the `/ovs/framework/scheduling/celery` JSON object. In this schedule X is the amount of months between each run.

In case the configuration cannot be parsed at all (e.g. invalid JSON), the code will fallback to the hardcoded schedule. If the crontab arguments are invalid (e.g. they contain an unsupported key) the task will be disabled.
