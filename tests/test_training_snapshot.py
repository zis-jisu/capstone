import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from rgae_service.repository import fetch_training_snapshot


class TrainingSnapshotRepositoryTests(unittest.TestCase):
    def test_fetches_requested_jsonb_snapshot(self):
        settings = SimpleNamespace(
            supabase_url="https://example.supabase.co",
            supabase_secret_key="secret",
            training_snapshot_table="graph_training_snapshots",
            training_snapshot_key="2026-10-01",
        )
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [{
            "snapshot_key": "2026-10-01",
            "snapshot_at": "2026-10-01T00:00:00+00:00",
            "source_file": "graph-1001.json",
            "graph_json": {"nodes": [{"id": "p1", "type": "Person"}], "edges": []},
        }]
        with patch("rgae_service.repository.httpx.get", return_value=response) as get:
            graph, metadata = fetch_training_snapshot(settings, "2026-10-01")

        self.assertEqual(graph["nodes"][0]["id"], "p1")
        self.assertEqual(metadata["snapshot_key"], "2026-10-01")
        self.assertEqual(get.call_args.kwargs["params"]["snapshot_key"], "eq.2026-10-01")

    def test_missing_snapshot_fails_closed(self):
        settings = SimpleNamespace(
            supabase_url="https://example.supabase.co",
            supabase_secret_key="secret",
            training_snapshot_table="graph_training_snapshots",
            training_snapshot_key="2026-10-01",
        )
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = []
        with patch("rgae_service.repository.httpx.get", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "2026-10-01"):
                fetch_training_snapshot(settings)


if __name__ == "__main__":
    unittest.main()
