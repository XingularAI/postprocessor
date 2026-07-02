# postprocessor-python-metadata-exporter — NX AI Manager post-processor

An external **post-processor** for the NX AI Manager that forwards detection
metadata to an HTTP backend in realtime. It is a *fire-and-forget* uploader
(`NoResponse: true`): it never modifies the pipeline output, it only sends data out.

Targets **Windows / Nx Witness**. Companion test backend: [`sample-backend/`](sample-backend/).
Deploy to other laptops: [`deploy/`](deploy/).

## Quick start (one command)

On the machine running Nx Witness + AI Manager, in an **elevated PowerShell**
(prerequisites below), run the one-shot installer — it builds, installs, sets the
`.ini`, registers the processor in `external_postprocessors.json`, and restarts the
Nx Witness Media Server:

```powershell
cd "<repo>\postprocessor-python-metadata-exporter"
powershell -ExecutionPolicy Bypass -File .\install.ps1
# optional: set the Backend URL shown in the NX UI
powershell -ExecutionPolicy Bypass -File .\install.ps1 -BackendUrl "http://127.0.0.1:8000/ingest"
```

Then in the NX Desktop Client: select **Metadata Exporter** on the camera and
enable **object tracking**. Done.

## What it does

Event-driven; sends only two kinds of events over HTTP POST:

- **`detect`** — a *new* object appeared. Deduplicated by the tracker's `ObjectID`
  (once per object, not every frame), with a JPEG **snapshot cropped to the object's bbox**.
- **`heartbeat`** — periodic status (`counts` per class) so the backend knows the camera is alive.

Highlights: dedupe by tracker ID (TTL-based), cropped snapshots, immediate (no-batch)
sending from a background thread with retry + backoff, and UI-configurable backend URL /
min confidence / heartbeat. `detect` requires **object tracking** in the pipeline (so
`ObjectID` exists); without it, only `heartbeat` is sent.

## Files

| File | Purpose |
|------|---------|
| `postprocessor-python-metadata-exporter.py` | The processor (source). |
| `plugin.metadata-exporter.ini` | Static config (installed to the `etc/` folder). |
| `requirements.txt` | Build/runtime Python deps (`nuitka, msgpack, requests, pillow, numpy`). |
| `CMakeLists.txt` | Build target (Nuitka one-file exe) + install rules. |
| `install.ps1` | One-shot build + install + register + restart (this machine, Nx Witness). |
| `sample-backend/` | Minimal Flask test backend (receives + prints events). |
| `deploy/` | Package + deploy scripts for moving the built processor to another laptop. |

## Requirements (Windows, one-time)

1. **Visual Studio 2022 Build Tools** with the **"Desktop development with C++"** workload
   (MSVC + Windows SDK). Needed to compile `nxai-c-utilities-shared.dll` and as Nuitka's C backend.
2. **CMake ≥ 3.30** (on `PATH`).
3. **Python 3.12** (64-bit, on `PATH`, with `venv` + `pip`).
4. **Git** with the `nxai-utilities` submodule fetched
   (`git submodule update --init --recursive` from the repo root).
5. **Internet access** on first build (CMake downloads Dependency Walker; pip downloads deps).
6. **Administrator** rights (the install target is under `systemprofile`).
7. A working **NX AI pipeline** with **object tracking enabled** (for `detect` events).

Quick install of the tools via winget:

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
winget install --id Kitware.CMake -e
winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --add Microsoft.VisualStudio.Component.Windows11SDK.22621 --includeRecommended"
```

> `install.ps1` **auto-activates the VS x64 build environment** (via `vswhere` + `Enter-VsDevShell`),
> so a plain **elevated PowerShell** is enough — you do **not** need the "x64 Native Tools Command Prompt".
> It prefers MSVC; if MSVC/Windows SDK can't be found, Nuitka falls back to auto-downloading Zig.

## Manual build / install (if you prefer not to use install.ps1)

The `Command` path and install destination must be the **Nx Witness** product folder.
`install.ps1` forces this via `-D` overrides; to do it by hand:

```
cmake -S . -B build "-DINSTALL_DEST_POSTPROCESSORS=C:\Windows\System32\config\systemprofile\AppData\Local\Network Optix\Network Optix Media Server\nx_ai_manager\nxai_manager\postprocessors"
cmake --build build --target postprocessor-python-metadata-exporter --config Release
cmake --install build --component postprocessor-python-metadata-exporter     # run in an elevated (Administrator) PowerShell
```

Then add the entry from [`deploy/external_postprocessors.entry.json`](deploy/external_postprocessors.entry.json)
to `...\Network Optix Media Server\nx_ai_manager\nxai_manager\postprocessors\external_postprocessors.json`
and restart: `Restart-Service "Network Optix Media Server"`.

## Configuration

UI settings override the `.ini`/code defaults; without the UI (dev/manual run) the `.ini`
and code fallbacks apply.

| Setting | Source | Notes |
|---------|--------|-------|
| `backend_url` | **NX UI** (prod) / code fallback (dev) | `http://127.0.0.1:8000/ingest` |
| `min_confidence` | **NX UI** (prod) / `0.0` (dev) | 0.0–1.0 |
| `heartbeat_seconds` | **NX UI** (prod) / `30` (dev) | 0 = off |
| `api_key` | `.ini` | sent as `Authorization: Bearer ...` (optional) |
| `send_snapshot` | `.ini` | must equal `ReceiveInputTensor` |
| `jpeg_quality`, `channel_order`, `snapshot_max_px` | `.ini` | snapshot encoding |
| `object_ttl_seconds` | `.ini` | dedupe TTL |
| `http_timeout`, `http_retries`, `queue_max` | `.ini` | resilience |
| `debug_level` | `.ini` `[common]` | `INFO` / `DEBUG` / ... |

Changing a UI value applies live (next frame). Changing the `.ini` requires a service restart.
The installed `.ini` lives in the `etc/` folder next to `postprocessors/`.

## Event schema

Both events carry an `event_id` (idempotency key). Times are **microseconds since epoch**.

```jsonc
// detect — a new tracked object
{
  "event_id": "<device>:<objectId>:detect",
  "type": "detect",
  "device_id": "cam-01",
  "device_name": "Front Gate",
  "timestamp": 1782901536165000,
  "sent_at":   1782901536170000,
  "object": { "id": "a1b2c3...", "class": "person", "confidence": 0.91,
              "bbox_xyxy": [412.0, 200.0, 680.0, 430.0], "attributes": {} },
  "frame": { "width": 1920, "height": 1080 },
  "snapshot": "<base64 JPEG string, bbox crop>"   // optional
}

// heartbeat — periodic status
{
  "event_id": "<device>:hb:<seconds>",
  "type": "heartbeat",
  "device_id": "cam-01",
  "device_name": "Front Gate",
  "sent_at": 1782901536170000,
  "counts": { "person": 2, "car": 1 }
}
```

## Testing

Start the test backend (see [`sample-backend/README.md`](sample-backend/README.md)), set the
Backend URL to `http://127.0.0.1:8000/ingest`, and watch events print in its terminal — one
`detect` per new object plus periodic `heartbeat`, no per-frame spam.

## Troubleshooting

- **`Could not find module 'nxai-c-utilities-shared.dll' (or one of its dependencies)`** — ensure the
  DLL is a **Release** build, install the **VC++ Redistributable x64**, and keep the DLL next to the exe.
- **`Connect to socket ... actively refused`** — nothing is listening: the exe crashed on startup, the
  `Command` path is wrong, or (dev) the script is not running / uses a different socket path.
- **No `detect` events, only heartbeats** — object tracking is not enabled in the pipeline.
- **Bounding boxes disappear in NX** — the AI Manager cannot reach the processor; get it listening.

## License

Copyright 2025, Network Optix. All rights reserved.
