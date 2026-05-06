#!/usr/bin/env python3
"""
Object Counter Threshold Postprocessor

This postprocessor counts the number of detected objects per category
and emits a custom event ONLY when the total count meets or exceeds
a configurable threshold.
"""

import os
import sys
import logging
import configparser
import signal
from threading import Event
from pprint import pformat

# Add the nxai-utilities python utilities
script_location = os.path.dirname(sys.argv[0])
sys.path.append(os.path.join(script_location, "../nxai-utilities/python-utilities"))
import nxai_communication_utils


CONFIG_FILE = os.path.join(script_location, "..", "etc", "plugin.object-counter-threshold.ini")

# Set up logging
if os.path.exists(os.path.join(script_location, "..", "etc")):
    LOG_FILE = os.path.join(script_location, "..", "etc", "plugin.object-counter-threshold.log")
else:
    LOG_FILE = os.path.join(script_location, "plugin.object-counter-threshold.log")

# Initialize plugin and logging
handler_stream = logging.StreamHandler(sys.stdout)
handler_stream.setLevel(logging.DEBUG)
handler_file = logging.FileHandler(filename=LOG_FILE, mode="w")
handler_file.setLevel(logging.INFO)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - object-counter-threshold - %(message)s",
    handlers=[handler_stream, handler_file]
)

# The name of the postprocessor
Postprocessor_Name = "External - Python-Object-Counter-Threshold-Postprocessor"

# The socket this postprocessor will listen on
import tempfile
Postprocessor_Socket_Path = os.path.join(tempfile.gettempdir(), "python-object-counter-threshold-postprocessor.sock")

# Shutdown event for graceful exit
shutdown_event = Event()

# Default threshold
DEFAULT_THRESHOLD = 5


def config():
    """Read configuration from INI file if available."""
    logger.info("Reading configuration from: " + CONFIG_FILE)

    try:
        configuration = configparser.ConfigParser()
        configuration.read(CONFIG_FILE)

        configured_log_level = configuration.get("common", "log_level", fallback="INFO")
        set_log_level(configured_log_level)

        for section in configuration.sections():
            logger.info("config section: " + section)
            for key in configuration[section]:
                logger.info("config key: " + key + " = " + configuration[section][key])

    except Exception as e:
        logger.error(e, exc_info=True)

    logger.debug("Read configuration done")


def set_log_level(level):
    """Set the logging level."""
    try:
        logger.setLevel(getattr(logging, level.upper()))
    except Exception as e:
        logger.error(e, exc_info=True)


def get_threshold_from_settings(input_object):
    """
    Extract the threshold parameter from the Settings field.

    Args:
        input_object: The input message dictionary.

    Returns:
        int: The threshold value, or DEFAULT_THRESHOLD if not found.
    """
    threshold = DEFAULT_THRESHOLD

    if "ExternalProcessorSettings" in input_object:
        # Look for the threshold setting
        # Settings format: {"externalprocessor.min_object_count": "10"}
        settings = input_object["ExternalProcessorSettings"]

        if "externalprocessor.min_object_count" in settings:
            try:
                threshold = int(settings["externalprocessor.min_object_count"])
                logger.debug(f"Threshold from settings: {threshold}")
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid threshold value in settings: {e}, using default {DEFAULT_THRESHOLD}")
                threshold = DEFAULT_THRESHOLD
    else:
        logger.warning("No external processor settings found, using default threshold: {}".format(DEFAULT_THRESHOLD))
    return threshold


def count_objects(input_object):
    """
    Count the number of objects per category from BBoxes_xyxy.

    Args:
        input_object: The input message dictionary containing BBoxes_xyxy.

    Returns:
        dict: A dictionary with category names as keys and counts as values.
    """
    counts = {}

    if "BBoxes_xyxy" not in input_object:
        return counts

    for class_name, class_coordinates in input_object["BBoxes_xyxy"].items():
        # Each bounding box is represented as [x1, y1, x2, y2]
        # So the number of objects is len(class_coordinates) / 4
        num_objects = len(class_coordinates) // 4
        if num_objects > 0:
            counts[class_name] = num_objects

    return counts


def format_count_description(counts, threshold):
    """
    Format the object counts into a human-readable description.

    Args:
        counts: Dictionary with category names and their counts.
        threshold: The threshold that was exceeded.

    Returns:
        str: Formatted description string.
    """
    if not counts:
        return "No objects detected in this frame."

    # Create a list of count strings
    count_parts = []
    total_objects = 0

    for category, count in sorted(counts.items()):
        count_parts.append(f"{count} {category}")
        total_objects += count

    # Build the description
    if len(count_parts) == 1:
        description = f"Detected {count_parts[0]}."
    else:
        description = f"Detected {', '.join(count_parts[:-1])} and {count_parts[-1]}."

    description += f" Total: {total_objects} object{'s' if total_objects != 1 else ''}."
    description += f" (Threshold: {threshold})"

    return description


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    signal_name = signal.Signals(signum).name
    logger.info(f"Received signal {signal_name}, initiating graceful shutdown...")
    shutdown_event.set()


def main():
    """Main postprocessor loop."""
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Start socket listener to receive messages from NXAI runtime
    server = nxai_communication_utils.SocketListener(Postprocessor_Socket_Path)

    # Wait for messages in a loop
    while not shutdown_event.is_set():
        # Wait for input message from runtime
        logger.debug("Waiting for input message")

        try:
            connection, input_message = server.accept()
            logger.debug("Received input message")
        except nxai_communication_utils.SocketTimeout:
            # Request timed out. Continue waiting
            continue
        except nxai_communication_utils.SocketError as e:
            logger.warning("An error occurred while receiving a socket message: " + str(e))
            continue

        # Parse input message
        input_object = nxai_communication_utils.parseInferenceResults(input_message)
        if isinstance(input_object, nxai_communication_utils.ExitSignal):
            logger.info("Received exit signal.")
            connection.close()
            break

        # Log the received data structure for debugging
        if logger.level == logging.DEBUG:
            formatted_unpacked_object = pformat(input_object)
            logger.debug(f"Unpacked:\n\n{formatted_unpacked_object}\n\n")

        # Get threshold from settings
        threshold = get_threshold_from_settings(input_object)

        # Count objects per category
        counts = count_objects(input_object)
        total_count = sum(counts.values())

        logger.info(f"Object counts: {counts}, Total: {total_count}, Threshold: {threshold}")

        # Only trigger event if threshold is met or exceeded
        if total_count >= threshold:
            # Format the description
            description = format_count_description(counts, threshold)

            logger.info(f"Threshold met! Triggering event.")
            logger.debug(f"Event description: {description}")

            # Add event to output
            if "Events" not in input_object:
                input_object["Events"] = []

            input_object["Events"].append({
                "ID": "object.counter.threshold",
                "Caption": "External - Object Count Threshold",
                "Description": description,
            })

            logger.info("Added object count threshold event to output")
        else:
            logger.debug(f"Threshold not met ({total_count} < {threshold}), no event triggered")

        # Write object back to bytes
        output_message = nxai_communication_utils.writeInferenceResults(input_object)

        # Send message back to runtime
        connection.send(output_message)
        connection.close()

    logger.info("Main loop exited, cleaning up...")


if __name__ == "__main__":
    # Initialize the logger
    logger = logging.getLogger(__name__)

    # Read configuration file if available
    config()

    logger.info("Initializing Object Counter Threshold Postprocessor")
    logger.debug("Input parameters: " + str(sys.argv))

    # Parse input arguments
    if len(sys.argv) > 1:
        Postprocessor_Socket_Path = sys.argv[1]

    logger.info(f"Socket path: {Postprocessor_Socket_Path}")
    logger.info(f"Default threshold: {DEFAULT_THRESHOLD}")

    # Start program
    try:
        main()
    except Exception as e:
        logger.error(e, exc_info=True)
    except KeyboardInterrupt:
        logger.info("Exited with keyboard interrupt")

    # Clean up socket file
    try:
        os.unlink(Postprocessor_Socket_Path)
    except OSError:
        if os.path.exists(Postprocessor_Socket_Path):
            logger.error("Could not remove socket file: " + Postprocessor_Socket_Path)
