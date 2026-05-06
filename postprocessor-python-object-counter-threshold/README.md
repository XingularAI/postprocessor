Postprocessor Python Object Counter Threshold
=============================================

Counts detected objects per category each frame and fires an event only when the total count meets or exceeds a configurable threshold.

This is useful for reducing event noise — alerts are only generated when a meaningful number of objects is present, rather than on every frame.

# Requirements

Any model that outputs bounding boxes.

# Configuration

Copy the [INI example](plugin.object-counter-threshold.ini.example) to:
```
/opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/nxai_manager/etc/plugin.object-counter-threshold.ini
```

The threshold is configurable via the NX AI Manager UI:

| Setting | Default | Description |
|---------|---------|-------------|
| `min_object_count` | 5 | Minimum total detected objects required to fire an event |

# How to build

```shell
mkdir -p build && cd build
python3 -m venv integrationsdk && source integrationsdk/bin/activate
cmake ..
cmake --build . --target postprocessor-python-object-counter-threshold
```

# How to install

```shell
cmake --install . --component postprocessor-python-object-counter-threshold
```

# Registration

Add to `external_postprocessors.json`:

```json
{
    "externalPostprocessors": [
        {
            "Name": "External - Object Counter with Threshold",
            "Command": "/opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/nxai_manager/postprocessors/postprocessor-python-object-counter-threshold",
            "SocketPath": "/tmp/python-object-counter-threshold-postprocessor.sock",
            "ReceiveInputTensor": false,
            "Events": [
                {
                    "ID": "object.counter.threshold",
                    "Name": "External - Object Count Threshold"
                }
            ],
            "Settings": [
                {
                    "type": "SpinBox",
                    "name": "externalprocessor.min_object_count",
                    "caption": "Minimum Object Count",
                    "description": "Trigger event only when total object count meets or exceeds this threshold",
                    "defaultValue": 5,
                    "minValue": 1,
                    "maxValue": 100
                }
            ]
        }
    ]
}
```

Then restart the NX Server:

```shell
sudo service networkoptix-metavms-mediaserver restart
```

# Logs

```shell
tail -f /opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/nxai_manager/etc/plugin.object-counter-threshold.log
```

# Licence

Copyright 2025, Network Optix, All rights reserved.
