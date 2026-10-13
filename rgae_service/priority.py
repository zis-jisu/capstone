from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


WEIGHTS = {"deadline": 0.40, "model": 0.30, "relation": 0.20, "workflow": 0.10}
RELATION_SCORES = {
    "APPROVES": 100,
    "APPROVER": 100,
    "RESPONSIBLE_FOR": 95,
    "OWNER": 95,
    "REVIEWS": 80,
    "REVIEWER": 80,
    "CONTRIBUTES_TO": 65,
    "COLLABORATOR": 65,
    "COORDINATES": 50,
    "BACKUP_FOR": 45,
    "RELATED": 35,
}
STATUS_SCORES = {
    "waiting": 70,
    "waiting_for_dependency": 70,
    "waiting_for_response": 70,
    "pending_review": 65,
    "in_progress": 60,
    "recurring": 45,
    "planned": 35,
}


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def rank_tasks(
    graph: dict[str, Any],
    person_id: str,
    candidate_task_ids: list[str],
    impact_by_task: dict[str, dict[str, float]],
    evaluated_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Apply the notebook's fixed 40/30/20/10 production priority formula."""
    evaluated_at = (evaluated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    node_by_id = {node["id"]: node for node in graph["nodes"]}
    candidate_set = set(candidate_task_ids)
    person_relations: dict[str, set[str]] = defaultdict(set)
    downstream: dict[str, set[str]] = defaultdict(set)
    for edge in graph["edges"]:
        source, target, relation = edge["source"], edge["target"], edge["relation"]
        if relation in RELATION_SCORES:
            if source == person_id and target in candidate_set:
                person_relations[target].add(relation)
            elif target == person_id and source in candidate_set:
                person_relations[source].add(relation)
        if relation == "DEPENDS_ON" and target in candidate_set:
            downstream_node = node_by_id.get(source, {})
            status = str(downstream_node.get("status", "")).lower()
            if downstream_node.get("type") == "Task" and status not in {"completed", "done", "closed"}:
                downstream[target].add(source)

    ordered_delta = sorted(
        (impact_by_task[task_id]["delta_error"], task_id) for task_id in candidate_task_ids
    )
    count = len(ordered_delta)
    model_score: dict[str, float] = {}
    for index, (value, task_id) in enumerate(ordered_delta):
        same = [i for i, item in enumerate(ordered_delta) if item[0] == value]
        average_rank = (same[0] + same[-1] + 2) / 2
        model_score[task_id] = average_rank / count * 100.0

    rows: list[dict[str, Any]] = []
    for task_id in candidate_task_ids:
        node = node_by_id[task_id]
        due_at = _parse_datetime(node.get("due_at"))
        if due_at is None:
            deadline_score = 10.0
        else:
            days = (due_at - evaluated_at).total_seconds() / 86400
            deadline_score = 100.0 if days < 0 else 95.0 if days <= 1 else 85.0 if days <= 3 else 70.0 if days <= 7 else 45.0 if days <= 30 else 25.0
        relations = person_relations[task_id]
        relation_score = 0.0
        if relations:
            relation_score = float(
                min(max(RELATION_SCORES[item] for item in relations) + max(0, len(relations) - 1) * 5, 100)
            )
        workflow_score = float(
            min(STATUS_SCORES.get(str(node.get("status", "")).lower(), 20) + min(len(downstream[task_id]), 2) * 15, 100)
        )
        composite = (
            WEIGHTS["deadline"] * deadline_score
            + WEIGHTS["model"] * model_score[task_id]
            + WEIGHTS["relation"] * relation_score
            + WEIGHTS["workflow"] * workflow_score
        )
        rows.append(
            {
                "task_id": task_id,
                "task_name": node.get("name"),
                "task_status": node.get("status"),
                "final_priority_score": round(composite, 4),
                "deadline_score": deadline_score,
                "model_score": round(model_score[task_id], 4),
                "relation_score": relation_score,
                "workflow_score": workflow_score,
                **{key: round(value, 8) for key, value in impact_by_task[task_id].items()},
            }
        )
    rows.sort(
        key=lambda row: (
            -row["final_priority_score"],
            -row["deadline_score"],
            -row["delta_error"],
            row["task_id"],
        )
    )
    for rank, row in enumerate(rows, 1):
        row["final_priority_rank"] = rank
    return rows

