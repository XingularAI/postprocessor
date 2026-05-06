Postprocessor Python Web Dashboard
===================================

Real-time object detection monitoring split into two independent components:

| Component | File | Role |
|-----------|------|------|
| **Postprocessor** | `postprocessor-python-web-dashboard.py` | Compiled binary; receives inference results from NX AI Manager, forwards them to the web app |
| **Web App** | `web_app.py` | Plain Python script; stores detection data in SQLite, serves a dashboard at `http://localhost:8111` |

## Architecture

```
NX AI Manager
    │  Unix socket (MessagePack)
    ▼
Postprocessor  (Nuitka-compiled binary)
    │  HTTP POST /api/ingest  (JSON)
    ▼
Web App  (web_app.py)
    │  SQLite  plugin.web-dashboard.db
    ▼
Browser Dashboard  http://localhost:8111
```

# Requirements

Any model that outputs bounding boxes. No additional Python packages required at runtime beyond the standard library.

# Configuration

Copy the [INI example](plugin.web-dashboard.ini.example) to:
```
/opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/nxai_manager/etc/plugin.web-dashboard.ini
```

Both components read the same INI file. Key settings:

| Section | Key | Default | Description |
|---------|-----|---------|-------------|
| `web_app` | `url` | `http://localhost:8111` | URL the postprocessor POSTs detection frames to |
| `web_server` | `port` | `8111` | Port the web app listens on |
| `web_server` | `timeline_capacity` | `50000` | Per-second timeline buckets to keep |
| `web_server` | `scatter_capacity` | `5000` | Reservoir sample size per scatter plot |

# How to build

Only the postprocessor binary is compiled; `web_app.py` runs directly with Python.

```shell
mkdir -p build && cd build
python3 -m venv integrationsdk && source integrationsdk/bin/activate
cmake ..
cmake --build . --target postprocessor-python-web-dashboard
```

# How to install

```shell
cmake --install . --component postprocessor-python-web-dashboard
```

This installs the postprocessor binary and `web_app.py` to the postprocessors directory.

# Registration

Add to `external_postprocessors.json`:

```json
{
    "externalPostprocessors": [
        {
            "Name": "External - Web Dashboard",
            "Command": "/opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/nxai_manager/postprocessors/postprocessor-python-web-dashboard",
            "SocketPath": "/tmp/python-web-dashboard-postprocessor.sock",
            "ReceiveInputTensor": false
        }
    ]
}
```

Restart the NX Server, then start the web app separately:

```shell
sudo service networkoptix-metavms-mediaserver restart
python3 /opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/nxai_manager/postprocessors/web_app.py
```

The dashboard is then available at `http://localhost:8111`.

# Running the web app

```shell
# With defaults
python3 web_app.py

# Override port or database path
python3 web_app.py --port 9000 --db /path/to/data.db
```

The web app restores all previously collected data from SQLite on startup, so it can be restarted independently of the postprocessor without data loss.

# Logs

| Component | Log file |
|-----------|----------|
| Postprocessor | `plugin.web-dashboard.log` |
| Web App | `plugin.web-dashboard-app.log` |

Both rotate at 10 MB, keeping 3 backups.

```shell
tail -f /opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/nxai_manager/etc/plugin.web-dashboard.log
tail -f /opt/networkoptix-metavms/mediaserver/var/nx_ai_manager/nxai_manager/etc/plugin.web-dashboard-app.log
```

# Troubleshooting

**Dashboard not loading** — confirm `web_app.py` is running and port 8111 is free.

**No data appearing** — run `curl http://localhost:8111/api/stats` to verify the web app is reachable, and check the postprocessor log for `Could not reach web app` warnings.

**Port conflict** — set `port` in `[web_server]` and `url` in `[web_app]` to a free port, then restart both components.

# Security

The web app binds to `0.0.0.0` with no authentication. For production deployments, put it behind a reverse proxy with authentication and HTTPS.

# Licence

Copyright 2025, Network Optix, All rights reserved.
