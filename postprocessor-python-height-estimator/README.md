Postprocessor Python Height Estimator
======================================

Estimates the height of detected persons from their bounding box dimensions and fires an event when any person exceeds a configurable height threshold.

For cameras where people walk left-to-right (bounding box height ≈ actual person height), the processor:
- Computes each detected person's height in metres using the configured pixels-per-metre ratio.
- Attaches an estimated `Height` attribute to every detected person object in the NX Client UI.
- Fires a `person.height.exceeded` event when any person's estimated height exceeds the configured limit.

# Requirements

Any model that outputs `person` bounding boxes (case-insensitive class name match).

# Configuration

Copy the [INI example](plugin.height-estimator.ini.example) to:
```
/opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/nxai_manager/etc/plugin.height-estimator.ini
```

Settings are configurable via the NX AI Manager UI:

| Setting | Default | Description |
|---------|---------|-------------|
| `pixels_per_meter` | 100 | Pixels that represent 1 metre in this camera view |
| `max_height_cm` | 250 | Height threshold in centimetres; exceeding it fires an event |

# How to build

```shell
mkdir -p build && cd build
python3 -m venv integrationsdk && source integrationsdk/bin/activate
cmake ..
cmake --build . --target postprocessor-python-height-estimator
```

# How to install

```shell
cmake --install . --component postprocessor-python-height-estimator
```

# Registration

Add to `external_postprocessors.json`:

```json
{
    "externalPostprocessors": [
        {
            "Name": "External - Person Height Estimator",
            "Command": "/opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/nxai_manager/postprocessors/postprocessor-python-height-estimator",
            "SocketPath": "/tmp/python-height-estimator-postprocessor.sock",
            "ReceiveInputTensor": false,
            "Events": [
                {
                    "ID": "person.height.exceeded",
                    "Name": "External - Person Height Exceeded"
                }
            ],
            "Settings": [
                {
                    "type": "SpinBox",
                    "name": "externalprocessor.pixels_per_meter",
                    "caption": "Pixels per Meter",
                    "description": "Number of pixels that represent 1 metre in this camera view",
                    "defaultValue": 100,
                    "minValue": 1,
                    "maxValue": 10000
                },
                {
                    "type": "SpinBox",
                    "name": "externalprocessor.max_height_cm",
                    "caption": "Maximum Height (cm)",
                    "description": "Trigger an event when a person's estimated height exceeds this value (centimetres)",
                    "defaultValue": 250,
                    "minValue": 50,
                    "maxValue": 500
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
tail -f /opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/nxai_manager/etc/plugin.height-estimator.log
```

# Licence

Copyright 2025, Network Optix, All rights reserved.
