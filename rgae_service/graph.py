from __future__ import annotations

import hashlib
import json
from collections import deque
from typing import Any


COMPLETED_STATUSES = {"completed", "complete", "done", "closed", "finished"}
HANDOFF_RELATIONS = {
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


def normalize_graph(raw: dict[str, Any]) -> dict[str, Any]:
    """Accept both notebook and API edge field names and return one schema."""
    if not isinstance(raw, dict):
        raise ValueError("graph_json must be a JSON object")
    nodes = raw.get("nodes")
    edges = raw.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("graph_json requires nodes and edges arrays")

    normalized_nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in nodes:
        node_id = str(node.get("id", "")).strip()
        node_type = str(node.get("type", "")).strip()
        if not node_id or not node_type:
            raise ValueError("every node requires id and type")
        if node_id in seen:
            raise ValueError(f"duplicate node id: {node_id}")
        seen.add(node_id)
        normalized_nodes.append(dict(node, id=node_id, type=node_type))

    normalized_edges: list[dict[str, Any]] = []
    for edge in edges:
        source = edge.get("source", edge.get("from"))
        target = edge.get("target", edge.get("to"))
        relation = edge.get("relation", edge.get("type"))
        if source is None or target is None or relation is None:
            raise ValueError("every edge requires source/target/relation (or from/to/type)")
        source, target, relation = str(source), str(target), str(relation)
        if source not in seen or target not in seen:
            raise ValueError(f"edge references an unknown node: {source} -> {target}")
        normalized_edges.append(
            dict(edge, source=source, target=target, relation=relation)
        )

    result = dict(raw, nodes=normalized_nodes, edges=normalized_edges)
    return result


def graph_digest(graph: dict[str, Any]) -> str:
    payload = json.dumps(
        graph, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def is_completed(node: dict[str, Any]) -> bool:
    if node.get("completed") is True:
        return True
    status = str(node.get("status", "")).strip().lower()
    return status in COMPLETED_STATUSES


def resolve_person(
    graph: dict[str, Any], person_id: str, person_name: str | None = None
) -> dict[str, Any]:
    node_by_id = {node["id"]: node for node in graph["nodes"]}
    person = node_by_id.get(person_id)
    if person is None:
        raise KeyError("person_id does not exist in the trained graph")
    if str(person.get("type", "")).lower() != "person":
        raise ValueError("person_id must identify a Person node")
    if person_name is not None and str(person.get("name", "")).strip() != person_name.strip():
        raise ValueError("person_name does not match person_id")
    return person


def overlay_live_task_fields(
    trained_graph: dict[str, Any], live_graph: dict[str, Any]
) -> dict[str, Any]:
    """Use current task fields without changing the topology used by the model."""
    live_nodes = {node["id"]: node for node in live_graph["nodes"]}
    nodes: list[dict[str, Any]] = []
    for trained_node in trained_graph["nodes"]:
        node = dict(trained_node)
        live_node = live_nodes.get(node["id"])
        if node.get("type") == "Task" and live_node is not None:
            for field in ("name", "status", "deadline_text", "due_at"):
                if field in live_node:
                    node[field] = live_node[field]
        nodes.append(node)
    return dict(trained_graph, nodes=nodes)


def two_hop_task_ids(
    graph: dict[str, Any], person_id: str, hops: int = 2
) -> list[str]:
    """Return every non-completed Task in an undirected N-hop ego graph."""
    node_by_id = {node["id"]: node for node in graph["nodes"]}
    if person_id not in node_by_id:
        raise KeyError(person_id)

    neighbors: dict[str, set[str]] = {node_id: set() for node_id in node_by_id}
    for edge in graph["edges"]:
        source, target = edge["source"], edge["target"]
        neighbors[source].add(target)
        neighbors[target].add(source)

    distance = {person_id: 0}
    queue = deque([person_id])
    while queue:
        current = queue.popleft()
        if distance[current] >= hops:
            continue
        for neighbor in neighbors[current]:
            if neighbor not in distance:
                distance[neighbor] = distance[current] + 1
                queue.append(neighbor)

    return sorted(
        node_id
        for node_id in distance
        if str(node_by_id[node_id].get("type", "")).lower() == "task"
        and not is_completed(node_by_id[node_id])
    )


def direct_task_ids(
    graph: dict[str, Any], person_ids: list[str]
) -> list[str]:
    """Return the active 1-hop role Tasks connected to any source person."""
    if not person_ids:
        raise ValueError("at least one source person_id is required")
    node_by_id = {node["id"]: node for node in graph["nodes"]}
    source_ids = set(person_ids)
    missing = sorted(source_ids - set(node_by_id))
    if missing:
        raise KeyError(f"person_id does not exist in the trained graph: {missing}")

    task_ids: set[str] = set()
    for edge in graph["edges"]:
        if edge["relation"] not in HANDOFF_RELATIONS:
            continue
        source, target = edge["source"], edge["target"]
        task_id = None
        if source in source_ids:
            task_id = target
        elif target in source_ids:
            task_id = source
        task = node_by_id.get(task_id or "")
        if task and str(task.get("type", "")).lower() == "task" and not is_completed(task):
            task_ids.add(task["id"])
    return sorted(task_ids)

