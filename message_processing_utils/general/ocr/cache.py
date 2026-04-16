"""
Cache for OCR recognition results.
"""

import time
from message_processing_utils.base.messages import InferenceMessage


class OcrCache:

    def __init__(self, engine, output_name, ocr_pool=None, ttl_sec: float = 300.0):
        self._ocr_results_cache = {}
        self._ocr_timestamps = {}
        self.engine = engine
        self.output_name = output_name
        self.ocr_pool = ocr_pool
        self.ttl_sec = ttl_sec

    def cache_ocr_result(self, message: InferenceMessage, recognized_text: str, confidence: float):
        if not message.original_object_id:
            return
        object_id = message.original_object_id
        self._ocr_results_cache[object_id] = (recognized_text, confidence)
        self._ocr_timestamps[object_id] = time.monotonic()

    def get_cached_result(self, object_id: str):
        return self._ocr_results_cache.get(object_id)

    def cleanup(self, current_time: float):
        """Remove entries older than ttl_sec."""
        expired = [
            oid for oid, ts in self._ocr_timestamps.items()
            if current_time - ts > self.ttl_sec
        ]
        for oid in expired:
            self._ocr_results_cache.pop(oid, None)
            self._ocr_timestamps.pop(oid, None)
