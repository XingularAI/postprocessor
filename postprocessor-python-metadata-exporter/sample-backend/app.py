"""
Sample test backend for the postprocessor-python-metadata-exporter post-processor.

- Accepts POST JSON from the post-processor on ANY path.
- DEDUPE by `event_id` (idempotency key): a payload whose event_id was already
  received is ignored (treated as a duplicate / retry).
- Prints a summary of each event to the terminal (long base64 blobs are shortened).
- Realtime-ready: every unique event is broadcast to an internal channel, and a
  `/stream` SSE endpoint is available for a dashboard later.

Run:  python app.py   (see README.md)
"""

import base64
import datetime
import json
import os
import queue
import threading
from collections import OrderedDict, deque

from flask import Flask, Response, request

app = Flask(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR = os.path.join(HERE, "snapshots")
SAVE_SNAPSHOTS = os.environ.get("SAVE_SNAPSHOTS", "0") == "1"
PORT = int(os.environ.get("PORT", "8000"))
DEDUPE_MAX = int(os.environ.get("DEDUPE_MAX", "50000"))   # number of event_ids remembered for dedupe

# ---- dedupe & pub/sub state (for SSE) ----
_seen = OrderedDict()                 # event_id -> True  (LRU for dedupe)
_seen_lock = threading.Lock()
_recent = deque(maxlen=200)           # short history for newly connected SSE clients
_subs = []                            # list of per-client SSE queues
_subs_lock = threading.Lock()
_counter = {"recv": 0, "dup": 0, "snap": 0}


def already_seen(event_id):
    """Return True if event_id was already received (duplicate); records it otherwise."""
    if not event_id:
        return False                  # no event_id: cannot dedupe, treat as unique
    with _seen_lock:
        if event_id in _seen:
            _seen.move_to_end(event_id)
            return True
        _seen[event_id] = True
        while len(_seen) > DEDUPE_MAX:
            _seen.popitem(last=False)  # drop the oldest
    return False


def publish(event):
    """Broadcast a unique event to all SSE clients and store it in history."""
    _recent.append(event)
    with _subs_lock:
        for q in list(_subs):
            try:
                q.put_nowait(event)
            except queue.Full:
                pass                   # slow client: skip (do not block ingest)


def summarize(obj):
    """Print-safe copy: long strings (e.g. base64) are shortened."""
    if isinstance(obj, dict):
        return {k: summarize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        if len(obj) > 24:
            return [summarize(v) for v in obj[:24]] + [f"...(+{len(obj) - 24} more)"]
        return [summarize(v) for v in obj]
    if isinstance(obj, str) and len(obj) > 120:
        return obj[:120] + f"...<{len(obj)} chars>"
    return obj


def maybe_save_snapshot(event):
    snap = event.get("snapshot") if isinstance(event, dict) else None
    if not (SAVE_SNAPSHOTS and isinstance(snap, str) and snap):   # snapshot = base64 JPEG string
        return None
    os.makedirs(SNAP_DIR, exist_ok=True)
    _counter["snap"] += 1
    name = str(event.get("event_id", _counter["snap"])).replace(":", "_").replace("/", "_")
    path = os.path.join(SNAP_DIR, f"{name}.jpg")
    try:
        with open(path, "wb") as f:
            f.write(base64.b64decode(snap))
        return path
    except Exception as e:            # noqa: BLE001
        print("  ! failed to save snapshot:", e)
        return None


@app.get("/health")
def health():
    return {"ok": True, "seen": len(_seen), "recv": _counter["recv"],
            "dup": _counter["dup"], "subscribers": len(_subs)}


@app.route("/", defaults={"path": ""}, methods=["POST"])
@app.route("/<path:path>", methods=["POST"])
def ingest(path):
    _counter["recv"] += 1
    now = datetime.datetime.now().strftime("%H:%M:%S")
    data = request.get_json(force=True, silent=True)
    if data is None:
        print(f"\n[{now}] ! body is not valid JSON. raw:", request.get_data()[:300])
        return {"ok": False, "error": "invalid json"}, 400

    event_id = data.get("event_id") if isinstance(data, dict) else None

    # ---- DEDUPE ----
    if already_seen(event_id):
        _counter["dup"] += 1
        print(f"[{now}] DUP ignored: {event_id}")
        return {"ok": True, "dedup": True}, 200

    etype = data.get("type", "?") if isinstance(data, dict) else "?"
    dev = data.get("device_id", "?") if isinstance(data, dict) else "?"

    print("\n" + "=" * 72)
    print(f"[{now}] EVENT type={etype}  device={dev}  id={event_id}")

    snap = data.get("snapshot") if isinstance(data, dict) else None
    if isinstance(snap, str):
        print(f"  snapshot: jpeg base64, {len(snap)} chars")
    saved = maybe_save_snapshot(data)
    if saved:
        print("  snapshot saved:", saved)

    disp = {**data, "snapshot": f"<jpeg base64, {len(snap)} chars>"} if isinstance(snap, str) else data
    print(json.dumps(summarize(disp), indent=2, ensure_ascii=False, default=str))

    publish(data)                      # broadcast to SSE (dashboard later)
    return {"ok": True}, 200


@app.get("/stream")
def stream():
    """SSE endpoint: a dashboard can later just do `new EventSource('/stream')`."""
    q = queue.Queue(maxsize=1000)
    with _subs_lock:
        _subs.append(q)

    def gen():
        try:
            yield ": connected\n\n"
            for ev in list(_recent)[-20:]:            # replay the last few events first
                yield f"data: {json.dumps(ev, default=str)}\n\n"
            while True:
                try:
                    ev = q.get(timeout=15)
                    yield f"data: {json.dumps(ev, default=str)}\n\n"
                except queue.Empty:
                    yield ": ping\n\n"                # keep-alive
        finally:
            with _subs_lock:
                if q in _subs:
                    _subs.remove(q)

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no",
                             "Connection": "keep-alive"})


if __name__ == "__main__":
    print(f"Metadata test backend  ->  http://0.0.0.0:{PORT}   (POST to any path)")
    print("Health check           ->  GET /health")
    print("SSE (dashboard later)  ->  GET /stream")
    print(f"Save snapshot JPEG     ->  set SAVE_SNAPSHOTS=1 (folder: {SNAP_DIR})")
    print("Dedupe by event_id is on. Duplicates are marked 'DUP ignored'.")
    print("-" * 72)
    app.run(host="0.0.0.0", port=PORT, threaded=True)
