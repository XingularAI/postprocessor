#!/usr/bin/env python3
"""
Web Dashboard Postprocessor
Receives inference results from NX AI Manager and forwards them to the web dashboard app.
"""
import os, sys, logging, logging.handlers, configparser, json, signal, time, urllib.request
from threading import Event
import tempfile

script_location = os.path.dirname(os.path.realpath(sys.argv[0]))
sys.path.append(os.path.join(script_location, "../nxai-utilities/python-utilities"))
import nxai_communication_utils

# ── Paths ─────────────────────────────────────────────────────────────────────
CONFIG_FILE = os.path.join(script_location, "..", "etc", "plugin.web-dashboard.ini")
_etc = os.path.join(script_location, "..", "etc")
LOG_FILE = os.path.join(
    _etc if os.path.exists(_etc) else script_location,
    "plugin.web-dashboard.log"
)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - web-dashboard - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=10_000_000, backupCount=3),
    ]
)

Postprocessor_Name = "External - Python-Web-Dashboard-Postprocessor"
Postprocessor_Socket_Path = os.path.join(
    tempfile.gettempdir(), "python-web-dashboard-postprocessor.sock"
)

DEFAULT_WEBAPP_URL = "http://localhost:8111"

shutdown_event = Event()
logger         = None


# ── Message processing ────────────────────────────────────────────────────────

def count_objects(msg):
    if 'BBoxes_xyxy' not in msg:
        return {}
    return {
        cls: len(coords) // 4
        for cls, coords in msg['BBoxes_xyxy'].items()
        if len(coords) >= 4
    }


def extract_bbox_data(msg):
    """Return flat lists of size and position dicts, each carrying a class label 'c'."""
    sizes, positions = [], []
    if 'BBoxes_xyxy' not in msg:
        return sizes, positions
    for cls, coords in msg['BBoxes_xyxy'].items():
        for i in range(0, len(coords) - 3, 4):
            x1, y1, x2, y2 = coords[i], coords[i+1], coords[i+2], coords[i+3]
            sizes.append({'x': round(abs(x2 - x1), 1), 'y': round(abs(y2 - y1), 1), 'c': cls})
            positions.append({'x': round((x1 + x2) / 2, 1), 'y': round((y1 + y2) / 2, 1), 'c': cls})
    return sizes, positions


def extract_timestamp(msg):
    """Return a Unix float (seconds) from the message Timestamp field.
    NX AI Manager may send microseconds (value > 1e12); fall back to wall clock."""
    ts = msg.get('Timestamp')
    if ts is None:
        return time.time()
    return ts / 1_000_000 if ts > 1e12 else float(ts)


# ── Web app communication ─────────────────────────────────────────────────────

def post_to_webapp(url, payload):
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url + '/api/ingest',
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception as e:
        logger.warning("Could not reach web app at %s: %s", url, e)
        return False


# ── Lifecycle ─────────────────────────────────────────────────────────────────

def signal_handler(signum, _):
    logger.info("Signal %s received, shutting down.", signal.Signals(signum).name)
    shutdown_event.set()


def set_log_level(level):
    try:
        logger.setLevel(getattr(logging, level.upper()))
    except Exception as e:
        logger.error("Log level error: %s", e, exc_info=True)


def config():
    logger.info("Reading config from: %s", CONFIG_FILE)
    webapp_url = DEFAULT_WEBAPP_URL
    try:
        cfg = configparser.ConfigParser()
        cfg.read(CONFIG_FILE)
        set_log_level(cfg.get('common', 'log_level', fallback='INFO'))
        webapp_url = cfg.get('web_app', 'url', fallback=DEFAULT_WEBAPP_URL)
    except Exception as e:
        logger.error("Config error: %s", e, exc_info=True)
    return webapp_url


def main(webapp_url):
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT,  signal_handler)

    if os.path.exists(Postprocessor_Socket_Path):
        try:
            os.unlink(Postprocessor_Socket_Path)
            logger.info("Removed stale socket file: %s", Postprocessor_Socket_Path)
        except OSError as e:
            logger.warning("Could not remove stale socket %s: %s", Postprocessor_Socket_Path, e)

    srv = nxai_communication_utils.SocketListener(Postprocessor_Socket_Path)

    while not shutdown_event.is_set():
        logger.debug("Waiting for message")
        conn = None
        try:
            conn, msg = srv.accept()
        except nxai_communication_utils.SocketTimeout:
            continue
        except nxai_communication_utils.SocketError as e:
            logger.warning("Socket error on accept: %s", e)
            continue
        except Exception as e:
            logger.error("Unexpected error on accept: %s", e, exc_info=True)
            continue

        try:
            obj = nxai_communication_utils.parseInferenceResults(msg)
            if isinstance(obj, nxai_communication_utils.ExitSignal):
                logger.info("Exit signal received.")
                break
            if not isinstance(obj, dict):
                logger.warning("Parsed message is not a dict (got %s), skipping",
                               type(obj).__name__)
                continue

            counts           = count_objects(obj)
            sizes, positions = extract_bbox_data(obj)
            ts               = extract_timestamp(obj)

            payload = {
                'ts':        ts,
                'counts':    counts,
                'sizes':     sizes,
                'positions': positions,
                'width':     obj.get('Width', 0),
                'height':    obj.get('Height', 0),
            }
            post_to_webapp(webapp_url, payload)
            logger.debug("Forwarded frame ts=%.3f counts=%s", ts, counts)

            conn.send(nxai_communication_utils.writeInferenceResults(obj))
        except Exception as e:
            logger.warning("Error processing message, skipping: %s", e)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    logger.info("Main loop exited.")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    logger = logging.getLogger(__name__)
    webapp_url = config()

    logger.info("Web Dashboard Postprocessor starting")
    if len(sys.argv) > 1:
        Postprocessor_Socket_Path = sys.argv[1]
    logger.info("Socket: %s | Web App: %s", Postprocessor_Socket_Path, webapp_url)

    try:
        main(webapp_url)
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)

    try:
        os.unlink(Postprocessor_Socket_Path)
    except OSError:
        if os.path.exists(Postprocessor_Socket_Path):
            logger.error("Could not remove socket: %s", Postprocessor_Socket_Path)
