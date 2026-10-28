import io
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from src import ml_bridge
from src import demo_frontend


class MlBridgePriorityTests(unittest.TestCase):
    def test_sequential_approvals_accumulate_sources_without_duplicates(self):
        approvals = [
            {"source_person_id": "U_KIM"},
            {"source_person_id": "U_PARK"},
            {"source_person_id": "U_KIM"},
        ]
        with patch.object(demo_frontend, "_handover_db", return_value=approvals) as handovers:
            sources = demo_frontend._approved_handoff_source_ids("U_WON")
        self.assertEqual(sources, ["U_KIM", "U_PARK"])
        self.assertEqual(handovers.call_args.kwargs["params"], {
            "select": "source_person_id",
            "requester_id": "eq.U_WON",
            "status": "eq.approved",
        })

    def test_multi_source_payload_is_deduplicated_and_has_receiver(self):
        response = io.BytesIO(b'{"rankings": {}}')
        with patch.object(ml_bridge, "_open", return_value=response) as opened:
            result = ml_bridge.priorities(
                person_ids=["U01", "U02", "U01"],
                receiver_person_id="U03",
            )
        self.assertEqual(result, {"rankings": {}})
        self.assertEqual(opened.call_args.kwargs["payload"], {
            "person_ids": ["U01", "U02"],
            "receiver_person_id": "U03",
        })

    def test_legacy_single_source_payload_is_preserved(self):
        response = io.BytesIO(b'{"rankings": {}}')
        with patch.object(ml_bridge, "_open", return_value=response) as opened:
            ml_bridge.priorities("U01")
        self.assertEqual(opened.call_args.kwargs["payload"], {"person_id": "U01"})

    def test_empty_sources_are_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            ml_bridge.priorities(person_ids=[])
        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
