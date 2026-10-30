import unittest
import math
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from rgae_service.api import PriorityRequest, priorities
from rgae_service.graph import direct_task_ids
from rgae_service.model import (
    build_model,
    prepare_graph,
    sample_negative_edges,
    task_impact_scores,
    train_model,
)
from rgae_service.priority import rank_tasks


class RgaeServiceTests(unittest.TestCase):
    def setUp(self):
        self.graph = {
            "nodes": [
                {"id": "p1", "type": "Person", "name": "Source One"},
                {"id": "p2", "type": "Person", "name": "Source Two"},
                {"id": "p3", "type": "Person", "name": "Other"},
                {"id": "t1", "type": "Task", "name": "Owner Task", "status": "waiting", "due_at": "2026-10-08T00:00:00Z"},
                {"id": "t2", "type": "Task", "name": "Related Task", "status": "in_progress", "due_at": "2026-10-08T00:00:00Z"},
                {"id": "t3", "type": "Task", "name": "Other Task", "status": "in_progress", "due_at": "2026-11-30T00:00:00Z"},
                {"id": "t4", "type": "Task", "name": "Completed", "status": "completed"},
                {"id": "t5", "type": "Task", "name": "Indirect", "status": "pending_review", "due_at": "2026-10-07T12:00:00Z"},
            ],
            "edges": [
                {"source": "p1", "target": "t1", "relation": "OWNER"},
                {"source": "p2", "target": "t2", "relation": "RELATED"},
                {"source": "p3", "target": "t3", "relation": "OWNER"},
                {"source": "p1", "target": "t4", "relation": "OWNER"},
                {"source": "t3", "target": "t1", "relation": "DEPENDS_ON"},
                {"source": "t5", "target": "t3", "relation": "DEPENDS_ON"},
                {"source": "t1", "target": "t5", "relation": "DEPENDS_ON"},
            ],
        }

    def test_multi_source_candidates_are_direct_active_union(self):
        self.assertEqual(direct_task_ids(self.graph, ["p1", "p2"]), ["t1", "t2"])

    def test_role_edge_weights_are_applied(self):
        prepared = prepare_graph(self.graph, seed=42)
        relation_weights = dict(
            zip(prepared["relation_names"], prepared["relation_weight_vector"].tolist())
        )
        self.assertEqual(relation_weights["OWNER"], 27)
        self.assertEqual(relation_weights["RELATED"], 4)
        self.assertEqual(relation_weights["DEPENDS_ON"], 15)

    def test_weighted_training_loss_runs(self):
        prepared = prepare_graph(self.graph, seed=42)
        model = build_model(prepared)
        loss = train_model(
            model,
            prepared,
            device=next(model.parameters()).device,
            epochs=1,
            seed=42,
        )
        self.assertTrue(math.isfinite(loss))

    def test_saturated_target_relation_corrupts_source(self):
        graph = {
            "nodes": [
                {"id": "p1", "type": "Person"},
                {"id": "p2", "type": "Person"},
                {"id": "team", "type": "Team"},
            ],
            "edges": [
                {"source": "p1", "target": "team", "relation": "MEMBER_OF"},
            ],
        }

        prepared = prepare_graph(graph, seed=42)
        negative_index, negative_type = sample_negative_edges(prepared, seed=42)

        self.assertEqual(negative_index.tolist(), [[1], [2]])
        self.assertEqual(negative_type.tolist(), [0])

    def test_priority_formula_uses_full_graph_percentile_and_related_penalty(self):
        impacts = {
            "t1": {"normal_error": 0.1, "counterfactual_error": 1.0, "delta_error": 0.9},
            "t2": {"normal_error": 0.1, "counterfactual_error": 0.2, "delta_error": 0.1},
            "t3": {"normal_error": 0.1, "counterfactual_error": 0.6, "delta_error": 0.5},
        }
        rows = rank_tasks(
            self.graph,
            ["p1", "p2"],
            ["t1", "t2"],
            impacts,
            evaluated_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
        )
        by_id = {row["task_id"]: row for row in rows}
        self.assertEqual(rows[0]["task_id"], "t1")
        self.assertEqual(by_id["t1"]["structure_score"], 100.0)
        self.assertAlmostEqual(by_id["t2"]["structure_score"], 33.3333, places=4)
        self.assertFalse(by_id["t1"]["related_only"])
        self.assertTrue(by_id["t2"]["related_only"])
        self.assertEqual(by_id["t2"]["related_penalty"], 10.0)
        self.assertEqual(by_id["t1"]["source_person_ids"], ["p1"])
        self.assertEqual(by_id["t2"]["source_person_ids"], ["p2"])
        self.assertEqual(by_id["t1"]["downstream_task_count"], 2)
        self.assertEqual(by_id["t1"]["effective_due_at"], "2026-10-07T12:00:00+00:00")
        self.assertEqual(by_id["t2"]["downstream_task_count"], 0)

    def test_workflow_status_buckets_use_other_as_twenty(self):
        graph = {
            "nodes": [
                {"id": "p1", "type": "Person"},
                {"id": "waiting", "type": "Task", "status": "waiting"},
                {"id": "progress", "type": "Task", "status": "in_progress"},
                {"id": "planned", "type": "Task", "status": "planned"},
                {"id": "review", "type": "Task", "status": "pending_review"},
                {"id": "recurring", "type": "Task", "status": "recurring"},
            ],
            "edges": [
                {"source": "p1", "target": task_id, "relation": "OWNER"}
                for task_id in ["waiting", "progress", "planned", "review", "recurring"]
            ],
        }
        impacts = {
            task_id: {"normal_error": 0.1, "counterfactual_error": 0.2, "delta_error": 0.1}
            for task_id in ["waiting", "progress", "planned", "review", "recurring"]
        }
        rows = rank_tasks(
            graph,
            "p1",
            ["waiting", "progress", "planned", "review", "recurring"],
            impacts,
            evaluated_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
        )
        scores = {row["task_id"]: row["workflow_score"] for row in rows}
        self.assertEqual(
            scores,
            {"waiting": 70.0, "progress": 60.0, "planned": 35.0, "review": 20.0, "recurring": 20.0},
        )

    def test_multi_source_counterfactual_removes_all_source_edges(self):
        prepared = prepare_graph(self.graph, seed=42)
        model = build_model(prepared)
        scores, removed_edges = task_impact_scores(
            model,
            prepared,
            ["p1", "p2"],
            device=next(model.parameters()).device,
            seed=42,
        )
        self.assertEqual(removed_edges, 3)
        self.assertTrue({"t1", "t2", "t3"}.issubset(scores))

    def test_api_returns_combined_1hop_ranking_and_receiver(self):
        prepared = prepare_graph(self.graph, seed=42)
        model = build_model(prepared)

        class FakeRuntime:
            device = next(model.parameters()).device

            @staticmethod
            def refresh_if_due():
                return None

            def snapshot(self):
                return self_graph, prepared, model, 42, {"trained_at": "2026-10-07T00:00:00Z"}

        self_graph = self.graph
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(runtime=FakeRuntime(), settings=object())
            )
        )
        body = PriorityRequest(
            person_ids=["p1", "p2"], receiver_person_id="p3"
        )
        with patch("rgae_service.api.fetch_graph", return_value=self.graph):
            response = priorities(request, body)

        self.assertEqual(response["candidate_scope"], "direct_1hop_active_tasks")
        self.assertEqual(
            response["priority_policy"],
            {
                "candidate_scope": "direct_1hop_active_tasks",
                "structure_weight": 55,
                "deadline_weight": 30,
                "workflow_weight": 15,
                "related_only_penalty": 10,
                "downstream_scope": "all_active_transitive_tasks",
                "workflow_status_scores": {
                    "waiting": 70,
                    "in_progress": 60,
                    "planned": 35,
                    "other": 20,
                },
            },
        )
        self.assertEqual(len(response["source_people"]), 2)
        self.assertEqual(response["receiver"]["person_id"], "p3")
        self.assertEqual(set(response["rankings"]), {"t1", "t2"})


if __name__ == "__main__":
    unittest.main()