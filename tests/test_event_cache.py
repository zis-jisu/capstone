"""Regression tests for source-validated Event checkpoint reuse."""
import tempfile
import unittest

from src.pipeline import run_pipeline
from tests.test_integration import source, model_call


class EventCacheTests(unittest.TestCase):
    def test_reuses_verified_events_without_recalling_event_llm(self):
        with tempfile.TemporaryDirectory() as cache:
            calls = {"event": 0}
            def wrapped(**kwargs):
                if "message" in kwargs["user_payload"]:
                    calls["event"] += 1
                return model_call(**kwargs)
            run_pipeline(source(), call=wrapped, event_cache_dir=cache)
            self.assertEqual(calls["event"], 1)
            run_pipeline(source(), call=wrapped, event_cache_dir=cache)
            self.assertEqual(calls["event"], 1)

    def test_changed_raw_text_invalidates_event_cache(self):
        with tempfile.TemporaryDirectory() as cache:
            calls = {"event": 0}
            def wrapped(**kwargs):
                if "message" in kwargs["user_payload"]:
                    calls["event"] += 1
                return model_call(**kwargs)
            run_pipeline(source(), call=wrapped, event_cache_dir=cache)
            modified = source()
            modified["messages"][0]["text"] += " 확인했습니다."
            run_pipeline(modified, call=wrapped, event_cache_dir=cache)
            self.assertEqual(calls["event"], 2)


if __name__ == "__main__":
    unittest.main()
