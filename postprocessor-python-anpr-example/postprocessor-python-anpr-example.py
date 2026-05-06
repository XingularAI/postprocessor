#!/usr/bin/env python3
"""
Postprocessor Python ANPR Example

This example postprocessor receives OCR results from the CCT model (NxM float32 logits)
and converts them to readable text by finding argmax for each character position.
"""

import atexit
import configparser
import hashlib
import logging
import os
import signal
import sys
import time

# Add message_processing_utils package to path
script_location = os.path.dirname(os.path.abspath(__file__))
if os.path.join(script_location, "..") not in sys.path:
    sys.path.insert(0, os.path.join(script_location, ".."))

from config_utils import (
    setup_logging,
    get_nxai_utilities_library_path,
    get_postprocessor_base_dir,
)
from message_processing_utils import create_anpr_message_from_bytes
from message_processing_utils.anpr import AnprDetectorMessage, EventDeduplicationCache
from message_processing_utils.general.ocr import (
    LogitsOcrEngine,
    OcrWorkerPool,
    OcrCache,
    load_ocr_config,
)

logger = logging.getLogger(__name__)

UI_SETTINGS_PREFIX = "externalprocessor."


def load_anpr_config(config_path, settings):
    """
    Load ANPR-specific configuration from INI file into settings dict.

    Args:
        config_path: Path to INI configuration file, or None.
        settings: Settings dictionary to update in-place.
    """
    settings["min_confidence"] = 0.95

    if config_path is None or not os.path.exists(config_path):
        return

    configuration = configparser.ConfigParser()
    configuration.read(config_path)

    if "anpr" in configuration:
        settings["min_confidence"] = configuration.getfloat(
            "anpr", "min_confidence", fallback=settings["min_confidence"]
        )


def _merge_anpr_settings(settings, ui_settings):
    """
    Merge INI/startup settings with per-message UI overrides.

    Args:
        settings: Base settings dict (from INI / load_anpr_config).
        ui_settings: ExternalProcessorSettings dict from current message.

    Returns:
        Dict with effective min_confidence for this message.
    """
    result = {"min_confidence": settings.get("min_confidence", 0.95)}

    if not isinstance(ui_settings, dict):
        return result

    key = UI_SETTINGS_PREFIX + "min_confidence"
    if key in ui_settings and ui_settings[key] is not None:
        try:
            result["min_confidence"] = float(ui_settings[key])
        except (TypeError, ValueError):
            pass

    return result


def _try_acquire_singleton_unix(socket_path):
    """Return (True, lock_path) if locked; (False, lock_path) if another instance holds it."""
    import fcntl
    lock_path = socket_path + ".singleton.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o666)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        try:
            os.close(fd)
        except OSError:
            pass
        return False, lock_path

    def _release():
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass

    atexit.register(_release)
    return True, lock_path


def _try_acquire_singleton_windows(socket_path):
    """
    Return (True, mutex_name) if this process owns the singleton mutex;
    (False, mutex_name) if another instance already holds it.
    """
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    CreateMutexW = kernel32.CreateMutexW
    CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    CreateMutexW.restype = wintypes.HANDLE
    CloseHandle = kernel32.CloseHandle
    CloseHandle.argtypes = [wintypes.HANDLE]
    CloseHandle.restype = wintypes.BOOL
    digest = hashlib.sha256(
        socket_path.encode("utf-8", errors="surrogateescape")
    ).hexdigest()[:32]
    mutex_names = (
        f"Global\\NxAiAnprPostprocessor-{digest}",
        f"Local\\NxAiAnprPostprocessor-{digest}",
    )
    ERROR_ALREADY_EXISTS = 183
    ERROR_ACCESS_DENIED = 5
    last_err = 0
    for mutex_name in mutex_names:
        kernel32.SetLastError(0)
        handle = CreateMutexW(None, False, mutex_name)
        err = kernel32.GetLastError()
        if not handle:
            last_err = kernel32.GetLastError()
            if last_err == ERROR_ACCESS_DENIED:
                continue
            raise OSError(last_err, f"CreateMutexW failed for {mutex_name!r}")
        if err == ERROR_ALREADY_EXISTS:
            CloseHandle(handle)
            return False, mutex_name

        def _release(h=handle):
            CloseHandle(h)

        atexit.register(_release)
        return True, mutex_name
    raise OSError(last_err, "CreateMutexW failed for all mutex name variants")


def _try_acquire_postprocessor_singleton(socket_path):
    """
    Ensure at most one postprocessor listener per socket_path across processes.
    Registers an atexit handler to release the lock on exit.
    Returns (ok, description) where description is lock file path or mutex name.
    Raises OSError on fatal errors (caller should log and exit non-zero).
    """
    if sys.platform == "win32":
        return _try_acquire_singleton_windows(socket_path)
    return _try_acquire_singleton_unix(socket_path)


def main(settings, engine, ocr_pool=None, event_cache=None):
    """Main postprocessor loop"""
    logger.info("=== STARTING ANPR POSTPROCESSOR ===")
    logger.info("Socket path: %s", settings["socket_path"])
    logger.info("Current working directory: %s", os.getcwd())

    # Add nxai_utilities to path
    if settings["nxai_utilities_path"] not in sys.path:
        sys.path.append(settings["nxai_utilities_path"])
    import nxai_communication_utils
    lib_path = get_nxai_utilities_library_path()
    if lib_path is not None:
        nxai_communication_utils.initializeLibrary(lib_path)
    server = nxai_communication_utils.SocketListener(settings["socket_path"])
    ocr_cache = OcrCache(engine, settings["ocr_output_name"], ocr_pool,
                         ttl_sec=settings.get("cache_ttl_sec", 300.0))
    while True:
        now = time.monotonic()
        ocr_cache.cleanup(now)
        if event_cache is not None:
            event_cache.cleanup(now)

        logger.debug("Waiting for input message")
        connection = None
        try:
            connection, input_message = server.accept()
            logger.debug("Received input message")
        except nxai_communication_utils.SocketTimeout:
            continue
        try:
            input_object = nxai_communication_utils.parseInferenceResults(input_message)
            if isinstance(input_object, nxai_communication_utils.ExitSignal):
                logger.info("Received exit signal.")
                connection.close()
                break
            message = create_anpr_message_from_bytes(input_message)
            logger.debug("Processing message: %s", message.__class__.__name__)
            message.handle(ocr_cache)

            if isinstance(message, AnprDetectorMessage) and event_cache is not None:
                ui_settings = message._message.get("ExternalProcessorSettings") or {}
                current = _merge_anpr_settings(settings, ui_settings)
                min_conf = current["min_confidence"]
                for object_id in set(message.object_ids):
                    cached = ocr_cache.get_cached_result(object_id)
                    if cached is None:
                        continue
                    text, conf = cached
                    if conf < min_conf:
                        continue
                    if event_cache.should_generate_event(object_id, text):
                        message.add_event(
                            "anpr.plate_recognized",
                            "License Plate Recognized",
                            text,
                        )
                        event_cache.mark_event_generated(object_id, text, time.monotonic())
                        logger.debug(
                            "Emitted plate_recognized event for object %s: %s (conf=%.4f)",
                            object_id, text, conf,
                        )

            try:
                connection.send(message.to_bytes())
            except Exception as e:
                logger.warning("Failed to send response: %s", e)
        except Exception as e:
            logger.error("Error processing message: %s", e, exc_info=True)
            try:
                connection.send(input_message)
            except Exception:
                pass
        finally:
            if connection is not None:
                connection.close()


if __name__ == "__main__":
    script_location = get_postprocessor_base_dir()
    config_file = os.path.join(script_location, "..", "etc", "plugin.anpr.ini")
    config_path = config_file if os.path.exists(config_file) else None

    settings = load_ocr_config(config_path, processor_name="anpr-example")
    load_anpr_config(config_path, settings)

    setup_logging(settings["log_level"], settings["log_file"], processor_name="anpr-example")
    if len(sys.argv) > 1:
        settings["socket_path"] = sys.argv[1]
    try:
        ok, lock_desc = _try_acquire_postprocessor_singleton(settings["socket_path"])
    except OSError as exc:
        logger.error("Singleton lock failed for socket %s: %s", settings["socket_path"], exc)
        sys.exit(1)
    if not ok:
        logger.warning(
            "Another ANPR postprocessor instance already holds %s; exiting so only "
            "one listener uses %s.",
            lock_desc,
            settings["socket_path"],
        )
        sys.exit(0)
    logger.info(
        "Singleton lock acquired (pid=%s, lock=%s, socket=%s)",
        os.getpid(),
        lock_desc,
        settings["socket_path"],
    )
    logger.debug("Input parameters: %s", sys.argv)
    logger.info("Configuration loaded:")
    for key, val in settings.items():
        logger.info("  %s = %s", key, val)
    if settings["nxai_utilities_path"] not in sys.path:
        sys.path.append(settings["nxai_utilities_path"])
    import nxai_communication_utils
    logger.info(
        "nxai_communication_utils loaded from %s", nxai_communication_utils.__file__)

    def _handle_sigterm(signum, frame):
        logger.info("Received SIGTERM — exiting")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_sigterm)
    try:
        engine = LogitsOcrEngine(
            expected_logits_shape=(9, 37),
            char_map="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ ",
        )
        pool = OcrWorkerPool(engine, settings["ocr_worker_count"])
        cache = EventDeduplicationCache(ttl_sec=settings["cache_ttl_sec"])
        main(settings, engine, pool, cache)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error("Unexpected error: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        if "pool" in locals():
            pool.stop()
