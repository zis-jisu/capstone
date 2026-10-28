from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


STRUCTURE_WEIGHT = 0.55
DEADLINE_WEIGHT = 0.30
WORKFLOW_WEIGHT = 0.15
RELATED_ONLY_PENALTY = 10.0
ROLE_RELATIONS = {
    "APPROVES",
    "APPROVER",
    "RESPONSIBLE_FOR",
    "OWNER",
    "REVIEWS",
    "REVIEWER",
    "CONTRIBUTES_TO",
    "COLLABORATOR",
    "RELATED",
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
COMPLETED_STATUSES = {"completed", "complete", "done", "closed", "finished"}


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _deadline_score(due_at: datetime | None, evaluated_at: datetime) -> float:
    if due_at is None:
        return 10.0
    days = (due_at - evaluated_at).total_seconds() / 86400
    if days < 0:
        return 100.0
    if days <= 1:
        return 95.0
    if days <= 3:
        return 85.0
    if days <= 7:
        return 70.0
    if days <= 30:
        return 45.0
    return 25.0


def _percentile_scores(
    graph: dict[str, Any], impact_by_task: dict[str, dict[str, float]]
) -> dict[str, float]:
    """Calculate structure percentiles on the full active Task graph."""
    node_by_id = {node["id"]: node for node in graph["nodes"]}
    values = sorted(
        (metrics["delta_error"], task_id)
        for task_id, metrics in impact_by_task.items()
        if task_id in node_by_id
        and str(node_by_id[task_id].get("type", "")).lower() == "task"
        and str(node_by_id[task_id].get("status", "")).lower()
        not in COMPLETED_STATUSES
    )
    count = len(values)
    if not count:
        return {}
    first_by_value: dict[float, int] = {}
    last_by_value: dict[float, int] = {}
    for index, (value, _task_id) in enumerate(values):
        first_by_value.setdefault(value, index)
        last_by_value[value] = index
    return {
        task_id: ((first_by_value[value] + last_by_value[value] + 2) / 2) / count * 100.0
        for value, task_id in values
    }


def rank_tasks(
    graph: dict[str, Any],
    person_ids: str | list[str],
    candidate_task_ids: list[str],
    impact_by_task: dict[str, dict[str, float]],
    evaluated_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Rank a union of direct handoff Tasks with the 55/30/15-minus-10 formula."""
    if isinstance(person_ids, str):
        person_ids = [person_ids]
    source_ids = set(person_ids)
    evaluated_at = (evaluated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    node_by_id = {node["id"]: node for node in graph["nodes"]}
    candidate_set = set(candidate_task_ids)
    task_relations: dict[str, set[str]] = defaultdict(set)
    task_sources: dict[str, set[str]] = defaultdict(set)
    downstream: dict[str, set[str]] = defaultdict(set)

    for edge in graph["edges"]:
        source, target, relation = edge["source"], edge["target"], edge["relation"]
        if relation in ROLE_RELATIONS:
            if source in source_ids and target in candidate_set:
                task_relations[target].add(relation)
                task_sources[target].add(source)
            elif target in source_ids and source in candidate_set:
                task_relations[source].add(relation)
                task_sources[source].add(target)
        if relation == "DEPENDS_ON" and target in candidate_set:
            downstream_node = node_by_id.get(source, {})
            status = str(downstream_node.get("status", "")).lower()
            if (
                str(downstream_node.get("type", "")).lower() == "task"
                and status not in COMPLETED_STATUSES
            ):
                downstream[target].add(source)

    model_score = _percentile_scores(graph, impact_by_task)
    rows: list[dict[str, Any]] = []
    for task_id in candidate_task_ids:
        node = node_by_id[task_id]
        effective_ids = {task_id} | downstream[task_id]
        due_dates = [
            parsed
            for item in effective_ids
            if (parsed := _parse_datetime(node_by_id[item].get("due_at"))) is not None
        ]
        effective_due_at = min(due_dates) if due_dates else None
        deadline_score = _deadline_score(effective_due_at, evaluated_at)
        workflow_score = float(
            min(
                STATUS_SCORES.get(str(node.get("status", "")).lower(), 20)
                + min(len(downstream[task_id]), 2) * 15,
                100,
            )
        )
        relations = task_relations[task_id]
        related_only = bool(relations) and relations == {"RELATED"}
        related_penalty = RELATED_ONLY_PENALTY if related_only else 0.0
        structure_score = model_score[task_id]
        composite = (
            STRUCTURE_WEIGHT * structure_score
            + DEADLINE_WEIGHT * deadline_score
            + WORKFLOW_WEIGHT * workflow_score
            - related_penalty
        )
        rows.append(
            {
                "task_id": task_id,
                "task_name": node.get("name"),
                "task_status": node.get("status"),
                "source_person_ids": sorted(task_sources[task_id]),
                "relations": sorted(relations),
                "related_only": related_only,
                "related_penalty": related_penalty,
                "final_priority_score": round(composite, 4),
                "structure_score": round(structure_score, 4),
                "deadline_score": deadline_score,
                "effective_due_at": effective_due_at.isoformat() if effective_due_at else None,
                "workflow_score": workflow_score,
                **{key: round(value, 8) for key, value in impact_by_task[task_id].items()},
            }
        )
    rows.sort(
        key=lambda row: (
            -row["final_priority_score"],
            -row["structure_score"],
            -row["deadline_score"],
            row["task_id"],
        )
    )
    for rank, row in enumerate(rows, 1):
        row["final_priority_rank"] = rank
    return rows
