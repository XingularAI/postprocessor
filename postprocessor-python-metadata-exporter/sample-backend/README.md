# Sample test backend

Minimal backend for testing `postprocessor-python-metadata-exporter`. It accepts POST JSON
from the post-processor, **drops duplicates by `event_id`**, prints a summary to the
terminal, and broadcasts every unique event to the **SSE** endpoint `/stream`
(ready for a realtime dashboard later).

## Setup (separate venv in this folder)

```powershell
cd "<repo>\postprocessor-python-metadata-exporter\sample-backend"
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # if blocked: Set-ExecutionPolicy -Scope Process -Bypass, then retry
pip install -r requirements.txt
```

## Run

```powershell
python app.py
```

- Listens on `http://0.0.0.0:8000`, accepts POST on **any path**.
- `GET /health` — status + event/duplicate counts.
- `GET /stream` — SSE for a dashboard (later): `new EventSource('http://localhost:8000/stream')`.
- Change the port: `$env:PORT="9000"; python app.py`
- Save snapshot JPEGs to `./snapshots`: `$env:SAVE_SNAPSHOTS="1"; python app.py`

## Point the post-processor at this backend

The backend URL is set from the **NX plugin Settings UI** ("Backend URL" control) →
`http://127.0.0.1:8000/ingest` (use `http`, not `https`). For dev/manual runs without the UI,
the fallback URL lives in the code / the `METADATA_EXPORTER_BACKEND_URL` env var.

## Event shapes received

There are only **2 types**. Every event has an `event_id` (idempotency key) used for dedupe.
Times (`timestamp`, `sent_at`) are in **microseconds since epoch**.

- **detect** — a new object was detected (deduped by tracker ID). `event_id = "<device>:<objectId>:detect"`.
  Fields: `device_id`, `device_name`, `timestamp`, `sent_at`, `object{id, class, confidence, bbox_xyxy, attributes}`,
  `frame{width, height}`, and `snapshot` (**base64 JPEG string**, bbox crop — optional).
- **heartbeat** — periodic status. `event_id = "<device>:hb:<seconds>"`.
  Fields: `device_id`, `device_name`, `sent_at`, `counts` (per-class counts).

`detect` only appears when the pipeline has **object tracking** (an `ObjectID` is present). The base64
snapshot is not printed in full to the terminal — only its length. Set `SAVE_SNAPSHOTS=1` to save the JPEGs.

## Notes

- This backend is plain HTTP with no auth — for local testing only. `api_key` (if set in the `.ini`) is sent
  as an `Authorization: Bearer ...` header and is only displayed, not validated.
- Backend and post-processor on the same machine → `127.0.0.1` is enough. Different machines → use the backend
  machine's IP and allow the port through Windows Firewall.
