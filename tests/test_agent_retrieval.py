import unittest

from src.agent_retrieval import retrieve_task_evidence


class FakeStore:
    def __init__(self):
        self.calls = []

    def request(self, table, *, params):
        self.calls.append((table, params))
        data = {
            "tasks": [{"task_id": "TASK-1", "title": "원고 검토"}],
            "edges": (
                [{"source_id": "TASK-1", "target_id": "EVENT-1", "relation": "HAS_EVENT"}]
                if params.get("relation") == "eq.HAS_EVENT" else
                [{"source_id": "WORK-1", "target_id": "TASK-1", "relation": "HAS_TASK"}]
            ),
            "events": [{"event_id": "EVENT-1", "source_id": "msg-1", "slack_ts": "100.1"}],
            "works": [{"work_id": "WORK-1", "title": "신차 출시"}],
            "slack_messages": [{"message_id": "msg-1", "text": "최종 승인 대기"}],
        }
        return data[table]


class RetrievalTest(unittest.TestCase):
    def test_graph_to_raw_message(self):
        store = FakeStore()
        result = retrieve_task_evidence("TASK-1", store)
        self.assertEqual(result["works"][0]["work_id"], "WORK-1")
        self.assertEqual(result["sources"][0]["message"]["text"], "최종 승인 대기")
        self.assertTrue(result["sources"][0]["raw_message_found"])
        self.assertTrue(all(params.get("limit") for _, params in store.calls))

    def test_missing_message_is_not_invented(self):
        class Missing(FakeStore):
            def request(self, table, *, params):
                if table == "slack_messages":
                    return []
                return super().request(table, params=params)

        result = retrieve_task_evidence("TASK-1", Missing())
        self.assertIsNone(result["sources"][0]["message"])
        self.assertFalse(result["sources"][0]["raw_message_found"])

    def test_invalid_limit(self):
        with self.assertRaises(ValueError):
            retrieve_task_evidence("TASK-1", FakeStore(), limit=0)


if __name__ == "__main__":
    unittest.main()
