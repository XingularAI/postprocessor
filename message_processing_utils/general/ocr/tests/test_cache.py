import time
import unittest

from message_processing_utils.general.ocr.cache import OcrCache


class _Msg:
    def __init__(self, object_id):
        self.original_object_id = object_id


class TestOcrCacheMaxConfidence(unittest.TestCase):

    def _cache(self, ttl_sec=300.0):
        return OcrCache(engine=None, output_name="Identity:0", ttl_sec=ttl_sec)

    def test_first_result_stored(self):
        cache = self._cache()
        cache.cache_ocr_result(_Msg("obj-1"), "ABC", 0.75)
        self.assertEqual(cache.get_cached_result("obj-1"), ("ABC", 0.75))

    def test_higher_confidence_overwrites(self):
        cache = self._cache()
        cache.cache_ocr_result(_Msg("obj-1"), "ABC", 0.75)
        cache.cache_ocr_result(_Msg("obj-1"), "A8C", 0.95)
        self.assertEqual(cache.get_cached_result("obj-1"), ("A8C", 0.95))

    def test_lower_confidence_does_not_overwrite(self):
        cache = self._cache()
        cache.cache_ocr_result(_Msg("obj-1"), "A8C", 0.95)
        cache.cache_ocr_result(_Msg("obj-1"), "ABC", 0.80)
        self.assertEqual(cache.get_cached_result("obj-1"), ("A8C", 0.95))

    def test_equal_confidence_does_not_overwrite(self):
        cache = self._cache()
        cache.cache_ocr_result(_Msg("obj-1"), "A8C", 0.95)
        cache.cache_ocr_result(_Msg("obj-1"), "ABC", 0.95)
        self.assertEqual(cache.get_cached_result("obj-1"), ("A8C", 0.95))

    def test_sequence_from_spec(self):
        # Frame 1: ABC@75, Frame 2: A8C@95, Frame 3: ABC@80 → should return A8C@95
        cache = self._cache()
        cache.cache_ocr_result(_Msg("obj-1"), "ABC", 0.75)
        cache.cache_ocr_result(_Msg("obj-1"), "A8C", 0.95)
        cache.cache_ocr_result(_Msg("obj-1"), "ABC", 0.80)
        self.assertEqual(cache.get_cached_result("obj-1"), ("A8C", 0.95))

    def test_timestamp_updated_on_lower_confidence(self):
        cache = self._cache(ttl_sec=1.0)
        cache.cache_ocr_result(_Msg("obj-1"), "A8C", 0.95)
        # Advance time past TTL by manipulating the stored timestamp
        cache._ocr_timestamps["obj-1"] -= 1.5
        # Lower-confidence write should refresh the timestamp
        cache.cache_ocr_result(_Msg("obj-1"), "ABC", 0.50)
        cache.cleanup(time.monotonic())
        # Entry must still be present (timestamp was refreshed)
        self.assertIsNotNone(cache.get_cached_result("obj-1"))
        # And the result must still be the best one
        self.assertEqual(cache.get_cached_result("obj-1"), ("A8C", 0.95))

    def test_cleanup_removes_expired(self):
        cache = self._cache(ttl_sec=1.0)
        cache.cache_ocr_result(_Msg("obj-1"), "ABC", 0.75)
        cache._ocr_timestamps["obj-1"] -= 2.0
        cache.cleanup(time.monotonic())
        self.assertIsNone(cache.get_cached_result("obj-1"))

    def test_no_object_id_ignored(self):
        cache = self._cache()
        cache.cache_ocr_result(_Msg(None), "ABC", 0.75)
        cache.cache_ocr_result(_Msg(""), "ABC", 0.75)
        self.assertEqual(cache._ocr_results_cache, {})


if __name__ == "__main__":
    unittest.main()
