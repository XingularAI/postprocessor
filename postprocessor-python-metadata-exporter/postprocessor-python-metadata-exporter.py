import os, sys, io, json, time, base64, queue, random, logging, threading, tempfile, configparser
import msgpack

script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
# SDK convention: config & log live in the sibling 'etc/' folder (next to 'postprocessors/').
# Fall back to the script folder for dev mode (when 'etc/' does not exist yet).
_etc = os.path.join(script_dir, "..", "etc")
_cfg_dir = _etc if os.path.isdir(_etc) else script_dir
CONFIG_FILE = os.path.join(_cfg_dir, "plugin.metadata-exporter.ini")
LOG_FILE    = os.path.join(_cfg_dir, "plugin.metadata-exporter.log")
# Python helpers from the nxai-utilities submodule (this folder must sit next to nxai-utilities/).
sys.path.append(os.path.join(script_dir, "..", "nxai-utilities", "python-utilities"))
import nxai_communication_utils as nx
_dll_path = os.path.join(script_dir, "nxai-c-utilities-shared.dll")
if os.path.exists(_dll_path):
    os.add_dll_directory(os.path.dirname(_dll_path))
    nx.initializeLibrary(_dll_path)   # load by full path before the SocketListener is created

try:
    import requests; _HTTP = "requests"
except ImportError:
    import urllib.request; _HTTP = "urllib"
try:
    import numpy as np
    from PIL import Image; _PIL = True
except ImportError:
    _PIL = False

# ---- configuration ----
cfg = configparser.ConfigParser(); cfg.read(CONFIG_FILE)
URL           = cfg.get("backend", "url",             fallback=os.environ.get("METADATA_EXPORTER_BACKEND_URL", "http://127.0.0.1:8000/ingest"))  # dev fallback; production via Settings UI
API_KEY       = cfg.get("backend", "api_key",         fallback=os.environ.get("METADATA_EXPORTER_API_KEY", ""))
SEND_SNAPSHOT = cfg.getboolean("backend", "send_snapshot",    fallback=True)   # must equal ReceiveInputTensor in the JSON
JPEG_QUALITY  = cfg.getint("backend", "jpeg_quality",         fallback=80)
CHANNEL_ORDER = cfg.get("backend", "channel_order",   fallback="RGB").upper()  # RGB or BGR
SNAPSHOT_MAX  = cfg.getint("backend", "snapshot_max_px",      fallback=640)     # longest crop side in px; 0 = no resize
HEARTBEAT_S   = cfg.getfloat("backend", "heartbeat_seconds",  fallback=30.0)    # dev fallback; production via Settings UI; 0 = off
OBJECT_TTL_S  = cfg.getfloat("backend", "object_ttl_seconds", fallback=5.0)
MIN_CONF      = cfg.getfloat("backend", "min_confidence",     fallback=0.0)     # dev fallback; production via Settings UI
HTTP_TIMEOUT  = cfg.getfloat("backend", "http_timeout",       fallback=5.0)
HTTP_RETRIES  = cfg.getint("backend", "http_retries",         fallback=2)
QUEUE_MAX     = cfg.getint("backend", "queue_max",            fallback=500)
LOG_LEVEL     = cfg.get("common", "debug_level",      fallback="INFO").upper()

# --- Settings UI (external_postprocessors.json -> "Settings"); NX sends values as STRINGS ---
# Names must start with 'externalprocessor.'; the 'metadata_' prefix avoids clashing with other
# processors' settings (NX sends ALL settings to ALL post-processors).
S_URL  = "externalprocessor.metadata_exporter_backend_url"
S_CONF = "externalprocessor.metadata_exporter_min_confidence"
S_HB   = "externalprocessor.metadata_exporter_heartbeat_seconds"

# Active runtime values: defaults from code, overridden each frame by the Settings UI (url, min_conf, heartbeat).
RUNTIME = {"url": URL, "api_key": API_KEY, "min_conf": MIN_CONF, "heartbeat_s": HEARTBEAT_S}

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(levelname)s - metadata-exporter - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_FILE, mode="a")],
)
log = logging.getLogger("metadata-exporter")

DEFAULT_SOCKET = os.path.join(tempfile.gettempdir(), "metadata-exporter.sock")

# ---- shared state (across frames; one processor instance serves all cameras) ----
_seen = {}            # (device_id, object_id) -> last_seen_ts   -> DETECT dedupe + TTL
_last_hb = {}         # device_id -> last heartbeat ts
_last_evict = [0.0]
_shm = {"key": None, "obj": None}

# =========================================================================
# Utilities
# =========================================================================
def compute_counts(obj):
    c = obj.get("Counts")
    if c:
        return {str(k): int(v) for k, v in c.items()}
    return {cls: len(coords) // 4 for cls, coords in obj.get("BBoxes_xyxy", {}).items()}

def read_shm(header):
    key = header["SHMKEY"]
    if _shm["key"] != key:                       # reopen if the segment key changed
        _shm["obj"] = nx.SharedMemory(key=key); _shm["key"] = key
    return _shm["obj"].read()

def decode_frame(header):
    """Read SHM once -> PIL RGB image (for cropping). None on failure / when PIL is unavailable."""
    if not _PIL or header is None:
        return None
    try:
        w, h, c = header["Width"], header["Height"], header["Channels"]
        arr = np.frombuffer(read_shm(header), dtype=np.uint8)
        if arr.size < w * h * c:
            return None
        arr = arr[: w * h * c].reshape(h, w, c)
        if c == 3 and CHANNEL_ORDER == "BGR":
            arr = np.ascontiguousarray(arr[:, :, ::-1])   # PIL requires a contiguous array
        mode = {1: "L", 3: "RGB", 4: "RGBA"}.get(c)
        if mode is None:
            return None
        return Image.fromarray(arr.reshape(h, w) if c == 1 else arr, mode).convert("RGB")
    except Exception as e:            # noqa: BLE001
        log.warning("decode_frame failed: %s", e)
        return None

def crop_encode(img, bbox, frame_w, frame_h):
    """Crop bbox (frame coordinate space) -> scale to image space if they differ -> JPEG base64 (string)."""
    sx = img.width / frame_w if frame_w else 1.0
    sy = img.height / frame_h if frame_h else 1.0
    x1, y1, x2, y2 = bbox
    box = (max(0, int(x1 * sx)), max(0, int(y1 * sy)),
           min(img.width, int(round(x2 * sx))), min(img.height, int(round(y2 * sy))))
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    crop = img.crop(box)
    if SNAPSHOT_MAX > 0 and max(crop.width, crop.height) > SNAPSHOT_MAX:
        crop.thumbnail((SNAPSHOT_MAX, SNAPSHOT_MAX))
    buf = io.BytesIO(); crop.save(buf, "JPEG", quality=JPEG_QUALITY)
    return base64.b64encode(buf.getvalue()).decode("ascii")

def _setting(s, name, cast, default):
    if name not in s:
        return default
    v = s[name]
    try:
        if cast is float: return float(v)     # NX sends numbers as strings, e.g. "0.5"
        if cast is int:   return int(float(v))
        return str(v)
    except Exception:      # noqa: BLE001
        return default

def apply_settings(obj):
    """Override RUNTIME from ExternalProcessorSettings (values from the plugin UI; sent every frame)."""
    s = obj.get("ExternalProcessorSettings") or {}
    if not s:
        return
    url = _setting(s, S_URL, str, RUNTIME["url"])
    if url:                                    # do not overwrite with an empty string
        RUNTIME["url"] = url
    RUNTIME["min_conf"]    = _setting(s, S_CONF, float, RUNTIME["min_conf"])
    RUNTIME["heartbeat_s"] = _setting(s, S_HB,   float, RUNTIME["heartbeat_s"])

def evict(now):
    if now - _last_evict[0] < OBJECT_TTL_S:
        return
    _last_evict[0] = now
    for k in [k for k, t in _seen.items() if now - t > OBJECT_TTL_S]:
        _seen.pop(k, None)

# =========================================================================
# Sending (separate thread; each event sent immediately = realtime; retry + backoff)
# =========================================================================
_q = queue.Queue(maxsize=QUEUE_MAX)

def enqueue(payload):
    job = (RUNTIME["url"], RUNTIME["api_key"], payload)   # capture the current url/api_key
    try:
        _q.put_nowait(job)
    except queue.Full:                 # backpressure: drop the oldest, keep the newest
        try: _q.get_nowait()
        except queue.Empty: pass
        try: _q.put_nowait(job)
        except queue.Full: pass
        log.warning("queue full, dropping oldest event")

def uploader():
    sess = requests.Session() if _HTTP == "requests" else None
    while True:
        job = _q.get()
        if job is None:
            break
        try:
            url, api_key, payload = job
            if not url:
                log.warning("backend URL is empty, event skipped (%s)", payload.get("event_id"))
                continue
            body = json.dumps(payload, default=str).encode("utf-8")
            headers = {"Content-Type": "application/json",
                       "X-Event-Id": str(payload.get("event_id", ""))}
            if api_key:
                headers["Authorization"] = "Bearer " + api_key
            for attempt in range(HTTP_RETRIES + 1):
                try:
                    if _HTTP == "requests":
                        r = sess.post(url, data=body, headers=headers, timeout=HTTP_TIMEOUT)
                        r.raise_for_status()
                    else:
                        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
                        urllib.request.urlopen(req, timeout=HTTP_TIMEOUT).close()
                    break
                except Exception as e:            # noqa: BLE001
                    if attempt < HTTP_RETRIES:
                        time.sleep(0.3 * (2 ** attempt) + random.uniform(0, 0.2))  # backoff + jitter
                    else:
                        log.warning("upload failed (%s): %s", payload.get("event_id"), e)
        finally:
            _q.task_done()

# =========================================================================
# Event builders (only 2: detect & heartbeat). Times are in MICROSECONDS (matching NX Timestamp).
# =========================================================================
def emit_detect(obj, now_us, dev, cls, oid, bbox, conf, attrs, snap, fw, fh):
    p = {"event_id": f"{dev}:{oid}:detect", "type": "detect",
         "device_id": dev, "device_name": obj.get("DeviceName"),
         "timestamp": obj.get("Timestamp"), "sent_at": now_us,
         "object": {"id": oid, "class": cls, "confidence": conf,
                    "bbox_xyxy": bbox, "attributes": attrs},
         "frame": {"width": fw, "height": fh}}
    if snap is not None:
        p["snapshot"] = snap                     # base64 JPEG string (bbox crop)
    enqueue(p)

def emit_heartbeat(obj, now_us, dev):
    enqueue({"event_id": f"{dev}:hb:{now_us // 1_000_000}", "type": "heartbeat",
             "device_id": dev, "device_name": obj.get("DeviceName"),
             "sent_at": now_us, "counts": compute_counts(obj)})

# =========================================================================
# Main loop
# =========================================================================
def handle_frame(obj, connection):
    now = time.time()
    now_us = int(now * 1_000_000)
    apply_settings(obj)                  # pick up the latest url, min_confidence & heartbeat from the Settings UI
    dev = obj.get("DeviceID", "") or ""
    fw = obj.get("Width") or 0
    fh = obj.get("Height") or 0

    # With ReceiveInputTensor:true (for snapshots) the AI Manager sends a 2nd message per frame.
    # It MUST be read (drained) so the socket does not desync — even if unused this frame.
    header = None
    if SEND_SNAPSHOT:
        try:
            header = msgpack.unpackb(connection.receive())
        except nx.SocketTimeout:
            log.warning("No image header received. Ensure ReceiveInputTensor:true in the JSON matches send_snapshot.")
        except Exception as e:            # noqa: BLE001
            log.warning("failed to read image header: %s", e)

    evict(now)
    frame_img = None                     # PIL image decoded lazily (only when there is a DETECT + snapshot)

    for cls, coords in (obj.get("BBoxes_xyxy", {}) or {}).items():
        meta  = (obj.get("ObjectsMetaData", {}) or {}).get(cls, {}) or {}
        ids   = meta.get("ObjectIDs") or []
        confs = meta.get("Confidences") or []
        akeys = meta.get("AttributeKeys") or []
        avals = meta.get("AttributeValues") or []
        for i in range(len(coords) // 4):
            conf = float(confs[i]) if i < len(confs) else None
            if conf is not None and conf < RUNTIME["min_conf"]:
                continue
            oid_raw = ids[i] if i < len(ids) else None
            if not oid_raw:                       # no tracker ID -> cannot dedupe -> skip
                continue                          # (enable object tracking in the pipeline to emit DETECT)
            oid = oid_raw.hex() if isinstance(oid_raw, (bytes, bytearray)) else str(oid_raw)
            key = (dev, oid)
            first = key not in _seen
            _seen[key] = now
            if not first:
                continue                          # already seen -> dedupe (not a new object)
            bbox = [float(x) for x in coords[i * 4:i * 4 + 4]]
            attrs = {}
            if i < len(akeys) and i < len(avals):
                try: attrs = {str(k): str(v) for k, v in zip(akeys[i], avals[i])}
                except Exception: attrs = {}      # noqa: BLE001
            snap = None
            if SEND_SNAPSHOT and header is not None:
                if frame_img is None:
                    frame_img = decode_frame(header)
                if frame_img is not None:
                    snap = crop_encode(frame_img, bbox, fw, fh)
            emit_detect(obj, now_us, dev, cls, oid, bbox, conf, attrs, snap, fw, fh)

    hb = RUNTIME["heartbeat_s"]
    if hb > 0 and now - _last_hb.get(dev, 0.0) >= hb:
        _last_hb[dev] = now
        emit_heartbeat(obj, now_us, dev)

def main(socket_path):
    threading.Thread(target=uploader, daemon=True).start()
    server = nx.SocketListener(socket_path)
    log.info("Listening on %s | backend=%s | snapshot=%s", socket_path, RUNTIME["url"], SEND_SNAPSHOT)
    while True:
        try:
            connection, input_message = server.accept()   # (connection, message)
        except nx.SocketTimeout:
            continue
        except nx.SocketError as e:
            log.warning("socket error: %s", e); continue

        obj = nx.parseInferenceResults(input_message)
        if isinstance(obj, nx.ExitSignal):
            log.info("Exit signal received."); connection.close(); break

        try:
            handle_frame(obj, connection)
        except Exception as e:            # noqa: BLE001
            log.warning("handle_frame error: %s", e)

        connection.close()               # NoResponse:true -> do not send a reply

if __name__ == "__main__":
    sock = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOCKET
    try:
        main(sock)
    except Exception as e:                # noqa: BLE001
        log.error(e, exc_info=True)
