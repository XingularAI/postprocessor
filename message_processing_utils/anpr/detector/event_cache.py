"""
Event deduplication cache for ANPR postprocessor.
"""


class EventDeduplicationCache:
    """
    Tracks (object_id → recognized text) pairs for which an event was already emitted.

    Prevents spamming the VMS with identical events when the same plate appears in
    consecutive frames. A new event is allowed when:
      - the object_id has not been seen before, OR
      - the recognized text changed for the same object_id.

    Entries expire after ttl_sec so stale tracks are eventually evicted.
    Call cleanup() once per processing loop iteration.
    """

    def __init__(self, ttl_sec: float = 300.0):
        self._cache = {}       # object_id → text
        self._timestamps = {}  # object_id → time.monotonic() of last event
        self.ttl_sec = ttl_sec

    def should_generate_event(self, object_id: str, text: str) -> bool:
        """Return True if an event should be generated for this object_id / text pair."""
        cached_text = self._cache.get(object_id)
        return cached_text is None or cached_text != text

    def mark_event_generated(self, object_id: str, text: str, current_time: float) -> None:
        """Record that an event was generated for object_id with the given text."""
        self._cache[object_id] = text
        self._timestamps[object_id] = current_time

    def cleanup(self, current_time: float) -> None:
        """Remove entries older than ttl_sec."""
        expired = [
            oid for oid, ts in self._timestamps.items()
            if current_time - ts > self.ttl_sec
        ]
        for oid in expired:
            self._cache.pop(oid, None)
            self._timestamps.pop(oid, None)
