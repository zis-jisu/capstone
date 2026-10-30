from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


PRIORITY_POLICY = {
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
}
STRUCTURE_WEIGHT = PRIORITY_POLICY["structure_weight"] / 100
DEADLINE_WEIGHT = PRIORITY_POLICY["deadline_weight"] / 100
WORKFLOW_WEIGHT = PRIORITY_POLICY["workflow_weight"] / 100
RELATED_ONLY_PENALTY = float(PRIORITY_POLICY["related_only_penalty"])
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
    "in_progress": 60,
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


def _active_downstream_tasks(
    graph: dict[str, Any], node_by_id: dict[str, dict[str, Any]]
) -> dict[str, set[str]]:
    """Return every active transitive Task that depends on each Task."""
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in graph["edges"]:
        if edge["relation"] != "DEPENDS_ON":
            continue
        source, target = edge["source"], edge["target"]
        if (
            str(node_by_id.get(source, {}).get("type", "")).lower() == "task"
            and str(node_by_id.get(target, {}).get("type", "")).lower() == "task"
        ):
            adjacency[target].add(source)

    downstream: dict[str, set[str]] = defaultdict(set)
    for task_id, node in node_by_id.items():
        if str(node.get("type", "")).lower() != "task":
            continue
        visited = {task_id}
        pending = list(adjacency[task_id])
        while pending:
            downstream_id = pending.pop()
            if downstream_id in visited:
                continue
            visited.add(downstream_id)
            downstream_node = node_by_id[downstream_id]
            if str(downstream_node.get("status", "")).lower() not in COMPLETED_STATUSES:
                downstream[task_id].add(downstream_id)
            pending.extend(adjacency[downstream_id])
    return downstream


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

    for edge in graph["edges"]:
        source, target, relation = edge["source"], edge["target"], edge["relation"]
        if relation in ROLE_RELATIONS:
            if source in source_ids and target in candidate_set:
                task_relations[target].add(relation)
                task_sources[target].add(source)
            elif target in source_ids and source in candidate_set:
                task_relations[source].add(relation)
                task_sources[source].add(target)
    downstream = _active_downstream_tasks(graph, node_by_id)

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
                "downstream_task_count": len(downstream[task_id]),
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