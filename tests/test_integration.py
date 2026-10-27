import copy
import json
import unittest
from unittest.mock import patch

from src.deadlines import normalize_deadline, db_timestamp, message_time
from src.db import to_db, export_graph, SupabaseStore
from src.pipeline import run_pipeline, assign_event_ids
from scripts.sync_slack import identity_conflicts, digest


def source():
    return {"people": [{"slack_id": "U01", "name": "김지수"}, {"slack_id": "U02", "name": "이정"}],
            "messages": [{"id": "C01:1791608400.000001", "channel": "C01", "author_id": "U01",
                          "timestamp": "2026-10-10T05:00:00Z",
                          "text": "이정씨, 계약서 내일 오전 10시까지 주세요. <https://example.com/guide|가이드>"}]}


def model_call(*, user_payload, **kwargs):
    if "message" in user_payload:
        return {"events": [{"source_id": "ignored", "subject": "계약서", "actor": {"slack_id": "U02", "name": "이정"},
            "requester": {"slack_id": "U01", "name": "김지수"}, "recipient": {"slack_id": "U02", "name": "이정"},
            "related_people": [], "action": "제출 요청", "event_type": "request", "status": "요청", "time_scope": "future",
            "deadline": {"text": "내일 오전 10시까지", "at": "2026-10-12T10:00:00+09:00"},
            "prerequisite": None, "constraint": None, "note": None, "certainty": "confirmed",
            "evidence": "이정씨, 계약서 내일 오전 10시까지 주세요."}]}, {}
    if "new_events" in user_payload:
        old = user_payload["existing_tasks"]
        event = user_payload["new_events"][0]
        return {"tasks": [{"task_id": old[0]["task_id"] if old else None, "title": "계약서 제출", "subject": "계약서",
            "status": "in_progress", "status_history": [], "deadline": event["deadline"], "next_action": "계약서 제출",
            "participants": [{"slack_id": "U02", "name": "이정", "roles": ["owner"], "event_ids": [event["event_id"]]}],
            "events": [{"event_id": event["event_id"], "role": "core"}], "task_links": [], "certainty": "confirmed"}]}, {}
    old = user_payload["existing_works"]
    return {"works": [{"work_id": old[0]["work_id"] if old else None, "title": "계약 체결",
                        "tasks": [{"task_id": user_payload["tasks"][0]["task_id"], "role": "core"}],
                        "certainty": "confirmed"}]}, {}


class DeadlineTests(unittest.TestCase):
    def test_relative_clock(self):
        self.assertEqual(normalize_deadline({"text": "내일 오전 10시까지", "at": None},
                         "2026-10-10T14:00:00+09:00")["at"], "2026-10-11T10:00:00+09:00")

    def test_kst_day_boundary(self):
        self.assertEqual(normalize_deadline({"text": "내일 오후 1시까지"},
                         "2026-10-10T16:00:00Z")["at"], "2026-10-12T13:00:00+09:00")

    def test_past_deadline_stays_past(self):
        self.assertEqual(normalize_deadline({"text": "오늘 오후 1시까지"},
                         "2026-10-10T14:00:00+09:00")["at"], "2026-10-10T13:00:00+09:00")

    def test_date_only_no_midnight(self):
        result = normalize_deadline({"text": "내일까지"}, "2026-10-10T05:00:00Z")
        self.assertEqual(result["at"], "2026-10-11")
        self.assertIsNone(db_timestamp(result["at"]))

    def test_unknown_date(self):
        self.assertIsNone(normalize_deadline({"text": "빠른 시일 내"})["at"])

    def test_missing_source_does_not_use_clock(self):
        self.assertIsNone(normalize_deadline({"text": "내일 오전 10시", "at": "2026-10-11"})["at"])

    def test_no_ampm_guess(self):
        self.assertEqual(normalize_deadline({"text": "내일 10시까지"}, "2026-10-10T05:00:00Z")["at"], "2026-10-11")

    def test_half_and_noon_midnight(self):
        for text, suffix in (("내일 오후 3시 반", "15:30"), ("내일 오전 12시", "00:00"), ("내일 오후 12시", "12:00")):
            self.assertEqual(normalize_deadline({"text": text}, "2026-10-10T05:00:00Z")["at"],
                             f"2026-10-11T{suffix}:00+09:00")

    def test_slack_ts_precision(self):
        self.assertEqual(message_time("1791608400.000001").microsecond, 1)

    def test_naive_source_rejected(self):
        with self.assertRaises(ValueError):
            message_time("2026-10-10T14:00:00")

    def test_multiple_clocks_ambiguous(self):
        self.assertIsNone(normalize_deadline({"text": "내일 오전 10시 또는 오후 2시"}, "2026-10-10T05:00:00Z")["at"])


class SupabaseStoreTests(unittest.TestCase):
    def test_mock_suffix_is_applied_only_when_requested(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self): return b'[]'

        urls = []

        def open_request(request, timeout=0):
            urls.append(request.full_url)
            return Response()

        with patch("urllib.request.urlopen", side_effect=open_request):
            SupabaseStore("https://example.supabase.co", "key").request("tasks")
            SupabaseStore("https://example.supabase.co", "key", table_suffix="_mock").request("tasks")
        self.assertEqual(urls, [
            "https://example.supabase.co/rest/v1/tasks",
            "https://example.supabase.co/rest/v1/tasks_mock",
        ])


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.result = run_pipeline(source(), call=model_call)
        self.bundle, self.warnings = to_db(self.result)

    def test_actual_source_overrides_wrong_llm_date(self):
        self.assertEqual(self.bundle["events"][0]["due_at"], "2026-10-11T10:00:00+09:00")
        self.assertEqual(self.bundle["tasks"][0]["deadline_at"], "2026-10-11T10:00:00+09:00")

    def test_links_and_raw_preserved(self):
        self.assertEqual(self.bundle["events"][0]["reference"], "https://example.com/guide")
        self.assertEqual(self.result["messages"][0]["raw_text"], source()["messages"][0]["text"])
        self.assertEqual(self.bundle["events"][0]["conversation_id"], "C01")

    def test_relations_and_graph(self):
        self.assertEqual({e["relation"] for e in self.bundle["edges"]},
                         {"ACTOR", "REQUESTER", "OWNER", "HAS_TASK", "HAS_EVENT"})
        graph = export_graph(self.bundle)
        self.assertEqual(graph["metadata"]["num_nodes"], 5)
        self.assertEqual(graph["metadata"]["relation_to_idx"]["ACTOR"], 7)
        self.assertEqual(len(graph["rgcn_tensors"]["edge_type"]), len(self.bundle["edges"]))

    def test_existing_task_dependency_is_exportable(self):
        data = copy.deepcopy(self.bundle)
        task_id = data["tasks"][0]["task_id"]
        data["edges"].append({"source_id": task_id, "source_type": "Task",
                              "relation": "DEPENDS_ON", "target_id": task_id,
                              "target_type": "Task", "evidence_event_ids": []})
        graph = export_graph(data)
        self.assertIn("DEPENDS_ON", [edge["relation"] for edge in graph["edges"]])

    def test_rerun_keeps_all_ids(self):
        rerun = run_pipeline(source(), snapshot=self.bundle, prior_result=self.result, call=model_call)
        for key, field in (("events", "event_id"), ("tasks", "task_id"), ("works", "work_id")):
            self.assertEqual(rerun[key][0][field], self.result[key][0][field])

    def test_status_change_keeps_id_and_history(self):
        old = copy.deepcopy(self.bundle)
        old["tasks"][0]["status"] = "waiting"
        rerun = run_pipeline(source(), snapshot=old, prior_result=self.result, call=model_call)
        self.assertEqual(rerun["tasks"][0]["task_id"], old["tasks"][0]["task_id"])
        self.assertEqual(rerun["tasks"][0]["status_history"][0]["from"], "waiting")

    def test_forwarded_request_not_speaker(self):
        result = copy.deepcopy(self.result)
        result["events"][0]["requester"] = None
        bundle, _ = to_db(result)
        self.assertNotIn("REQUESTER", {e["relation"] for e in bundle["edges"]})

    def test_extra_task_roles_map_without_inventing_owner(self):
        result = copy.deepcopy(self.result)
        task = result["tasks"][0]
        event_id = result["events"][0]["event_id"]
        task["participants"].extend([
            {"slack_id": "U01", "name": "김지수", "roles": ["follow-up owner"], "event_ids": [event_id]},
            {"slack_id": "U01", "name": "김지수", "roles": ["recipient", "requester"], "event_ids": [event_id]},
        ])
        bundle, warnings = to_db(result)
        edges = {(e["source_id"], e["relation"], e["target_id"]) for e in bundle["edges"]}
        self.assertIn(("U01", "RELATED", task["task_id"]), edges)
        self.assertNotIn(("U01", "OWNER", task["task_id"]), edges)
        self.assertIn(("U01", "REQUESTER", event_id), edges)
        self.assertFalse(any(w["type"] == "role_not_in_ml_schema" for w in warnings))

    def test_unresolved_prerequisite_preserved(self):
        result = copy.deepcopy(self.result)
        result["events"][0]["prerequisite"] = "최종 승인 후"
        result["events"][0]["constraint"] = "외부 공유 금지"
        bundle, warnings = to_db(result)
        self.assertEqual(bundle["events"][0]["prerequisite"], "최종 승인 후")
        self.assertEqual(bundle["events"][0]["memo"], "외부 공유 금지")
        self.assertNotIn("DEPENDS_ON", {e["relation"] for e in bundle["edges"]})
        self.assertTrue(any(w["type"] == "unresolved_prerequisite" for w in warnings))

    def test_dangling_edge_blocked(self):
        result = copy.deepcopy(self.result)
        result["tasks"][0]["events"].append({"event_id": "missing", "role": "core"})
        with self.assertRaises(ValueError):
            to_db(result)

    def test_edited_single_fact_keeps_id(self):
        edited = copy.deepcopy(self.result["events"])
        edited[0]["evidence"] = "계약서 오늘 오전 11시까지 주세요."
        assign_event_ids(edited, self.bundle["events"])
        self.assertEqual(edited[0]["event_id"], self.bundle["events"][0]["event_id"])

    def test_ambiguous_retirement_blocked(self):
        with self.assertRaises(ValueError):
            assign_event_ids([], self.bundle["events"])

    def test_synthetic_identity_conflict(self):
        conflicts = identity_conflicts(self.bundle, {"persons": [{"person_id": "PERSON-01", "name": "김지수"}]})
        self.assertEqual(len(conflicts), 1)
    def test_save_preserves_existing_edges(self):
        class FakeStore(SupabaseStore):
            def __init__(self):
                self.calls = []

            def request(self, table, **kwargs):
                self.calls.append((table, kwargs))
                return []

        old = copy.deepcopy(self.bundle)
        tid = old["tasks"][0]["task_id"]

        old["edges"].extend([
            {
                "source_id": "Uold",
                "source_type": "Person",
                "relation": "OWNER",
                "target_id": tid,
                "target_type": "Task"
            },
            {
                "source_id": "Uother",
                "source_type": "Person",
                "relation": "OWNER",
                "target_id": "TASK-other",
                "target_type": "Task"
            }
        ])

        store = FakeStore()
        store.save(self.bundle, old)

        deletes = [
            kw for _, kw in store.calls
            if kw["method"] == "DELETE"
        ]

        # 부분 동기화 시 기존 엣지를 삭제하지 않는지 검증
        self.assertEqual(len(deletes), 0)

    def test_digest_order_independent(self):
        reordered = copy.deepcopy(self.bundle)
        reordered["edges"].reverse()
        self.assertEqual(digest(self.bundle), digest(reordered))


if __name__ == "__main__":
    unittest.main()
