#!/usr/bin/env python3
"""
Person Height Estimator Postprocessor

For cameras where people walk left-to-right (bounding box height ≈ person height),
this postprocessor:
  - Estimates every detected person's height in meters from their bounding box.
  - Attaches the estimated height as a "Height" attribute on each person object.
  - Fires an event when any person's height exceeds the configured threshold.

User-configurable settings (via NX Cloud Pipelines UI):
  - pixels_per_meter : how many pixels correspond to 1 metre in this camera view.
  - max_height_cm    : height threshold in centimetres; exceeding it fires an event.
"""

import os
import sys
import logging
import configparser
import signal
from threading import Event
from pprint import pformat

script_location = os.path.dirname(sys.argv[0])
sys.path.append(os.path.join(script_location, "../nxai-utilities/python-utilities"))
import nxai_communication_utils


CONFIG_FILE = os.path.join(script_location, "..", "etc", "plugin.height-estimator.ini")

if os.path.exists(os.path.join(script_location, "..", "etc")):
    LOG_FILE = os.path.join(script_location, "..", "etc", "plugin.height-estimator.log")
else:
    LOG_FILE = os.path.join(script_location, "plugin.height-estimator.log")

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - height-estimator - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(filename=LOG_FILE, mode="w"),
    ]
)

Postprocessor_Name = "External - Python-Height-Estimator-Postprocessor"

import tempfile
Postprocessor_Socket_Path = os.path.join(
    tempfile.gettempdir(), "python-height-estimator-postprocessor.sock"
)

DEFAULT_PIXELS_PER_METER = 100
DEFAULT_MAX_HEIGHT_CM    = 250    # 2.50 m

shutdown_event = Event()


# ── Configuration ─────────────────────────────────────────────────────────────

def config():
    logger.info("Reading configuration from: %s", CONFIG_FILE)
    try:
        cfg = configparser.ConfigParser()
        cfg.read(CONFIG_FILE)
        set_log_level(cfg.get("common", "log_level", fallback="INFO"))
        for section in cfg.sections():
            for key, value in cfg[section].items():
                logger.info("config [%s] %s = %s", section, key, value)
    except Exception as e:
        logger.error(e, exc_info=True)


def set_log_level(level):
    try:
        logger.setLevel(getattr(logging, level.upper()))
    except Exception as e:
        logger.error(e, exc_info=True)


def get_settings(input_object):
    """Extract pixels_per_meter and max_height_m from ExternalProcessorSettings."""
    pixels_per_meter = DEFAULT_PIXELS_PER_METER
    max_height_m     = DEFAULT_MAX_HEIGHT_CM / 100.0

    settings = input_object.get("ExternalProcessorSettings", {})
    if not settings:
        logger.warning("No ExternalProcessorSettings found, using defaults.")
        return pixels_per_meter, max_height_m

    try:
        pixels_per_meter = int(settings.get(
            "externalprocessor.pixels_per_meter", DEFAULT_PIXELS_PER_METER
        ))
        max_height_cm = int(settings.get(
            "externalprocessor.max_height_cm", DEFAULT_MAX_HEIGHT_CM
        ))
        max_height_m = max_height_cm / 100.0
    except (ValueError, TypeError) as e:
        logger.warning("Invalid settings value: %s. Using defaults.", e)

    return pixels_per_meter, max_height_m


# ── Processing ────────────────────────────────────────────────────────────────

def find_person_class(input_object):
    """Return the person class key from BBoxes_xyxy (case-insensitive)."""
    for cls in input_object.get("BBoxes_xyxy", {}):
        if cls.lower() == "person":
            return cls
    return None


def add_height_attributes(input_object, pixels_per_meter):
    """
    Compute and attach an estimated height attribute to every detected person.

    The attribute is added to ObjectsMetaData so NX displays it on each
    tracked object in the UI.

    Returns:
        list[float]: Estimated height in metres for each detected person,
                     in the same order as the bounding boxes.
    """
    person_class = find_person_class(input_object)
    if person_class is None:
        return []

    bboxes = input_object["BBoxes_xyxy"][person_class]
    n = len(bboxes) // 4
    if n == 0:
        return []

    # Ensure ObjectsMetaData and the person entry exist
    if "ObjectsMetaData" not in input_object:
        input_object["ObjectsMetaData"] = {}

    ometa = input_object["ObjectsMetaData"]
    if person_class not in ometa:
        ometa[person_class] = {
            "ObjectIDs":      ["" for _ in range(n)],
            "AttributeKeys":  [[] for _ in range(n)],
            "AttributeValues":[[] for _ in range(n)],
        }

    meta = ometa[person_class]

    # Guard against mismatched array lengths (e.g. stale metadata)
    for field in ("AttributeKeys", "AttributeValues"):
        if not isinstance(meta.get(field), list) or len(meta[field]) != n:
            meta[field] = [[] for _ in range(n)]

    heights = []
    for i in range(n):
        y1 = bboxes[i * 4 + 1]
        y2 = bboxes[i * 4 + 3]
        height_m = abs(y2 - y1) / pixels_per_meter
        heights.append(height_m)

        meta["AttributeKeys"][i].append("Height")
        meta["AttributeValues"][i].append(f"{height_m:.2f} m")

    return heights


def build_event(heights, max_height_m):
    """
    Return an event dict if any height exceeds max_height_m, else None.

    The description summarises how many persons exceeded and by how much.
    """
    exceeding = sorted(
        [h for h in heights if h > max_height_m],
        reverse=True
    )
    if not exceeding:
        return None

    tallest   = exceeding[0]
    threshold = max_height_m
    count     = len(exceeding)
    total     = len(heights)

    description = (
        f"{count} of {total} detected person(s) exceed the height limit of "
        f"{threshold:.2f} m. "
        f"Tallest: {tallest:.2f} m."
    )

    return {
        "ID":          "person.height.exceeded",
        "Caption":     "Person Height Exceeded",
        "Description": description,
    }


# ── Main loop ─────────────────────────────────────────────────────────────────

def signal_handler(signum, _frame):
    logger.info("Signal %s received, shutting down.", signal.Signals(signum).name)
    shutdown_event.set()


def main():
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT,  signal_handler)

    server = nxai_communication_utils.SocketListener(Postprocessor_Socket_Path)

    while not shutdown_event.is_set():
        logger.debug("Waiting for input message")

        try:
            connection, input_message = server.accept()
        except nxai_communication_utils.SocketTimeout:
            continue
        except nxai_communication_utils.SocketError as e:
            logger.warning("Socket error: %s", e)
            continue

        input_object = nxai_communication_utils.parseInferenceResults(input_message)
        if isinstance(input_object, nxai_communication_utils.ExitSignal):
            logger.info("Exit signal received.")
            connection.close()
            break

        if logger.level == logging.DEBUG:
            logger.debug("Unpacked:\n%s", pformat(input_object))

        pixels_per_meter, max_height_m = get_settings(input_object)

        # Always add height attributes to all detected persons
        heights = add_height_attributes(input_object, pixels_per_meter)
        logger.debug("Person heights (m): %s", [round(h, 2) for h in heights])

        # Fire an event only when someone exceeds the threshold
        event = build_event(heights, max_height_m)
        if event:
            input_object.setdefault("Events", []).append(event)
            logger.info("Height event fired: %s", event["Description"])

        output_message = nxai_communication_utils.writeInferenceResults(input_object)
        connection.send(output_message)
        connection.close()

    logger.info("Main loop exited.")


if __name__ == "__main__":
    logger = logging.getLogger(__name__)
    config()

    logger.info("Initializing Person Height Estimator Postprocessor")
    logger.debug("Arguments: %s", sys.argv)

    if len(sys.argv) > 1:
        Postprocessor_Socket_Path = sys.argv[1]

    logger.info("Socket: %s", Postprocessor_Socket_Path)
    logger.info("Defaults — pixels/m: %d, max height: %.2f m",
                DEFAULT_PIXELS_PER_METER, DEFAULT_MAX_HEIGHT_CM / 100.0)

    try:
        main()
    except Exception as e:
        logger.error(e, exc_info=True)
    except KeyboardInterrupt:
        logger.info("Exited with keyboard interrupt")

    try:
        os.unlink(Postprocessor_Socket_Path)
    except OSError:
        if os.path.exists(Postprocessor_Socket_Path):
            logger.error("Could not remove socket: %s", Postprocessor_Socket_Path)
