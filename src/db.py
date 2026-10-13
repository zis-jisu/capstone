"""Adapter for the existing five-table Supabase schema (no schema mutation)."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from src.deadlines import db_timestamp

TABLE_KEYS = {"persons": "person_id", "events": "event_id", "tasks": "task_id", "works": "work_id",
              "edges": "source_id,relation,target_id"}
NODE_TYPES = {"Person": 0, "Task": 1, "Work": 2, "Event": 3}
# Matches graph/export_graph.py, including the reserved REQUESTER relation.
RELATIONS = {"HAS_TASK": 0, "HAS_EVENT": 1, "OWNER": 2, "APPROVER": 3,
             "REVIEWER": 4, "COLLABORATOR": 5, "RELATED": 6, "ACTOR": 7,
             "REQUESTER": 8, "DEPENDS_ON": 9}
ALLOWED = {"HAS_TASK": {("Work", "Task")}, "HAS_EVENT": {("Task", "Event")},
           "OWNER": {("Person", "Task")}, "APPROVER": {("Person", "Task")},
           "REVIEWER": {("Person", "Task")}, "COLLABORATOR": {("Person", "Task")},
           "RELATED": {("Person", "Task"), ("Person", "Event")},
           "ACTOR": {("Person", "Event")}, "REQUESTER": {("Person", "Event")},
           "DEPENDS_ON": {("Event", "Event"), ("Task", "Task")}}


class SupabaseStore:
    def __init__(self, url=None, key=None):
        self.url = (url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.key = key or os.environ.get("SUPABASE_KEY", "")
        if not self.url.startswith("https://") or not self.key:
            raise ValueError("Configure SUPABASE_URL and a backend-only SUPABASE_KEY.")

    def request(self, table, *, params=None, method="GET", rows=None):
        if table not in TABLE_KEYS and table != "slack_messages":
            raise ValueError("Unknown pipeline table.")
        url = self.url + "/rest/v1/" + table
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, method=method,
            data=None if rows is None else json.dumps(rows, ensure_ascii=False).encode(),
            headers={"apikey": self.key, "Authorization": "Bearer " + self.key,
                     "Content-Type": "application/json",
                     "Prefer": "resolution=merge-duplicates,return=minimal"})
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                raw = response.read()
                return json.loads(raw) if raw else []
        except urllib.error.HTTPError as exc:
            # Don't include response bodies or URLs that may disclose credentials.
            raise RuntimeError(f"Supabase {table} {method} failed: HTTP {exc.code}") from None

    def fetch(self, table):
        rows, offset = [], 0
        order = ",".join(k + ".asc" for k in TABLE_KEYS[table].split(","))
        while True:
            batch = self.request(table, params={"select": "*", "order": order,
                                               "limit": 500, "offset": offset})
            rows.extend(batch)
            if len(batch) < 500:
                return rows
            offset += len(batch)

    def snapshot(self):
        return {table: self.fetch(table) for table in TABLE_KEYS}

    def upsert(self, table, rows):
        for start in range(0, len(rows), 200):
            self.request(table, method="POST", params={"on_conflict": TABLE_KEYS[table]},
                         rows=rows[start:start + 200])

    def preflight_raw_message_schema(self):
        """Fail closed unless the raw message schema has been reviewed.

        Set SLACK_MESSAGES_SCHEMA_VERIFIED=1 only after confirming that
        message_id, author_id, author_name, channel, conversation_id,
        thread_id, conversation_type, slack_ts, parent_ts, timestamp,
        text, reference_urls and raw_json exist, and that other required
        columns have defaults or permit NULL.
        """
        if os.environ.get("SLACK_MESSAGES_SCHEMA_VERIFIED") != "1":
            raise RuntimeError(
                "Raw-message schema not confirmed. Review public.slack_messages "
                "columns and NOT NULL constraints, then set "
                "SLACK_MESSAGES_SCHEMA_VERIFIED=1 in a test environment."
            )

    def save_messages(self, messages, people):
        """Upsert original Slack text without clearing existing task/work links.

        Save persons first: author_id references persons(person_id).
        Recollecting an edited message updates the existing message_id.
        """
        names = {p["slack_id"]: p["name"] for p in people}
        rows = []
        for message in messages:
            author_id = message["slack_id"]
            if author_id not in names:
                raise ValueError(f"Unknown Slack author: {author_id}")
            rows.append({
                "message_id": message["source_id"],
                "author_id": author_id,
                "author_name": names[author_id],
                "channel": message["channel"],
                "conversation_id": message["channel"],
                "thread_id": message.get("thread_key"),
                "conversation_type": message.get("conversation_type", "unknown"),
                "slack_ts": message["timestamp"],
                "parent_ts": message.get("parent_ts"),
                "timestamp": message["timestamp"],
                "text": message["raw_text"],
                "reference_urls": message.get("reference_urls", []),
                "raw_json": message,
            })
        for start in range(0, len(rows), 200):
            self.request("slack_messages", method="POST",
                         params={"on_conflict": "message_id"},
                         rows=rows[start:start + 200])
        return rows

    def save(self, bundle, before):
        """Upsert nodes then edges; remove only obsolete affected relationships.

        REST writes are not a cross-table transaction. Caller must persist its full
        bundle before calling save; individual upserts reuse the same IDs.
        No global edge wipe, no removal of unrelated tasks or dependency edges.
        """
        old = {(e["source_id"], e["relation"], e["target_id"]): e for e in before.get("edges", [])}
        new = {(e["source_id"], e["relation"], e["target_id"]): e for e in bundle["edges"]}
        affected_tasks = {t["task_id"] for t in bundle["tasks"]}
        affected_events = {e["event_id"] for e in bundle["events"]}
        affected_works = {w["work_id"] for w in bundle["works"]}
        for table in ("persons", "works", "tasks", "events", "edges"):
            self.upsert(table, bundle[table])
        # Preserve existing edges. Partial extraction is not an authoritative
        # deletion request; retirement requires a separate reviewed workflow.
        pass


def to_db(result, before=None):
    before = before or {}
    people = {p["slack_id"]: {"person_id": p["slack_id"], "name": p["name"], "aliases": []}
              for p in result.get("people", []) if p.get("slack_id")}
    bundle = {table: [] for table in TABLE_KEYS}
    warnings = []
    edges = {}

    def person(obj):
        if not obj or not obj.get("slack_id"):
            return None
        pid = obj["slack_id"]
        if pid not in people:
            raise ValueError(f"Unregistered person ID: {pid}")
        return pid

    def edge(source, stype, relation, target, ttype, evidence=()):
        if not source:
            return
        if (stype, ttype) not in ALLOWED.get(relation, set()):
            raise ValueError(f"Unsupported relation: {stype} {relation} {ttype}")
        key = source, relation, target
        item = edges.setdefault(key, {"source_id": source, "source_type": stype,
                   "relation": relation, "target_id": target, "target_type": ttype,
                   "evidence_event_ids": []})
        item["evidence_event_ids"] = sorted(set(item["evidence_event_ids"]) | set(evidence))

    for e in result.get("events", []):
        actor, recipient = e.get("actor") or {}, e.get("recipient") or {}
        deadline = e.get("deadline") or {}
        memo = "\n".join(str(e[k]) for k in ("constraint", "note") if e.get(k)) or None
        references = e.get("reference_urls", [])
        bundle["events"].append({
            "event_id": e["event_id"], "source_id": e["source_id"],
            "speaker": e.get("speaker"), "speaker_id": e.get("speaker_id"),
            "slack_user_id": e.get("speaker_id"), "slack_ts": e.get("slack_ts"),
            "conversation_id": e.get("conversation_id"), "conversation_type": e.get("conversation_type"),
            "parent_ts": e.get("parent_ts"), "subject": e.get("subject"),
            "actor": actor.get("name"), "actor_id": person(actor),
            "recipient": recipient.get("name"), "recipient_id": person(recipient),
            "related_people": e.get("related_people", []), "action": e.get("action"),
            "event_type": e.get("event_type"), "status": e.get("status"),
            "time_scope": e.get("time_scope"), "deadline_text": deadline.get("text"),
            "due_at": db_timestamp(deadline.get("at")), "memo": memo,
            # Keep the original condition too: unresolved dependencies must not disappear.
            "prerequisite": e.get("prerequisite"), "certainty": e.get("certainty"),
            "evidence": e.get("evidence"), "reference": "\n".join(references) or None,
            "updated_at": result.get("processed_at")})
        edge(person(actor), "Person", "ACTOR", e["event_id"], "Event", [e["event_id"]])
        if e.get("event_type") == "request":
            edge(person(e.get("requester")), "Person", "REQUESTER", e["event_id"], "Event", [e["event_id"]])
        for p in e.get("related_people", []):
            edge(person(p), "Person", "RELATED", e["event_id"], "Event", [e["event_id"]])
        if e.get("prerequisite"):
            warnings.append({"type": "unresolved_prerequisite", "event_id": e["event_id"], "text": e["prerequisite"]})
        if deadline.get("at") and len(deadline["at"]) == 10:
            warnings.append({"type": "date_without_time", "event_id": e["event_id"], "date": deadline["at"]})

    for t in result.get("tasks", []):
        d = t.get("deadline") or {}
        bundle["tasks"].append({k: t.get(k) for k in ("task_id", "title", "subject", "status", "next_action", "certainty")}
                               | {"deadline_text": d.get("text"), "deadline_at": db_timestamp(d.get("at")),
                                  "updated_at": result.get("processed_at")})
        for e in t.get("events", []):
            edge(t["task_id"], "Task", "HAS_EVENT", e["event_id"], "Event", [e["event_id"]])
        for p in t.get("participants", []):
            # Keep the DB relation vocabulary fixed. Do not equate a future
            # handoff recipient with the currently responsible OWNER.
            participant_id = person(p)
            for role in p.get("roles", []):
                normalized_role = role.strip().lower().replace("-", "_").replace(" ", "_")
                relation = {
                    "owner": "OWNER",
                    "collaborator": "COLLABORATOR",
                    "reviewer": "REVIEWER",
                    "approver": "APPROVER",
                    "related": "RELATED",
                    "recipient": "RELATED",
                    "follow_up_owner": "RELATED",
                    "requester": "RELATED",
                }.get(normalized_role)
                if relation:
                    edge(participant_id, "Person", relation, t["task_id"], "Task", p.get("event_ids", []))
                else:
                    warnings.append({"type": "role_not_in_ml_schema", "task_id": t["task_id"], "role": role})
                # REQUESTER is Person -> Event, created above only when the
                # Event itself explicitly identifies the true requester.
        if t.get("task_links"):
            warnings.append({"type": "task_links_not_in_ml_schema", "task_id": t["task_id"]})
    for w in result.get("works", []):
        bundle["works"].append({k: w.get(k) for k in ("work_id", "title", "certainty")}
                               | {"updated_at": result.get("processed_at")})
        for t in w.get("tasks", []):
            edge(w["work_id"], "Work", "HAS_TASK", t["task_id"], "Task")
    bundle["persons"] = list(people.values())
    bundle["edges"] = list(edges.values())
    # Validate IDs against both unchanged DB rows and new rows before any write.
    nodes = {}
    for table, kind in (("persons", "Person"), ("works", "Work"), ("tasks", "Task"), ("events", "Event")):
        for row in before.get(table, []) + bundle[table]:
            key = row[TABLE_KEYS[table]]
            if key in nodes and nodes[key] != kind:
                raise ValueError(f"Node ID reused across types: {key}")
            nodes[key] = kind
    for e in bundle["edges"]:
        if nodes.get(e["source_id"]) != e["source_type"] or nodes.get(e["target_id"]) != e["target_type"]:
            raise ValueError("Edge references a missing or wrong-type node.")
        if any(nodes.get(i) != "Event" for i in e["evidence_event_ids"]):
            raise ValueError("Edge evidence references a missing Event.")
    return bundle, warnings


def export_graph(snapshot):
    """Build graph and ML indices wholly from DB, with dynamic counts."""
    nodes = []
    for table, kind in (("persons", "Person"), ("tasks", "Task"), ("works", "Work"), ("events", "Event")):
        nodes.extend(dict(row, id=row[TABLE_KEYS[table]], type=kind)
                     for row in sorted(snapshot.get(table, []), key=lambda r: r[TABLE_KEYS[table]]))
    index = {n["id"]: i for i, n in enumerate(nodes)}
    if len(index) != len(nodes):
        raise ValueError("Duplicate node ID across tables.")
    kinds = {n["id"]: n["type"] for n in nodes}
    edges, sources, targets, types = [], [], [], []
    for e in sorted(snapshot.get("edges", []), key=lambda e: (e["source_id"], e["relation"], e["target_id"])):
        src, dst, rel = e["source_id"], e["target_id"], e["relation"]
        if (kinds.get(src), kinds.get(dst)) not in ALLOWED.get(rel, set()):
            raise ValueError("Invalid DB edge or missing node.")
        if kinds[src] != e["source_type"] or kinds[dst] != e["target_type"]:
            raise ValueError("DB edge node type mismatch.")
        edges.append({"source": src, "target": dst, "relation": rel,
                      "evidence_event_ids": e.get("evidence_event_ids", [])})
        sources.append(index[src]); targets.append(index[dst]); types.append(RELATIONS[rel])
    return {"metadata": {"num_nodes": len(nodes), "num_edges": len(edges),
                         "num_relation_types": len(RELATIONS), "node_type_to_idx": NODE_TYPES,
                         "relation_to_idx": RELATIONS},
            "nodes": nodes, "edges": edges,
            "rgcn_tensors": {"edge_index": [sources, targets], "edge_type": types,
                             "node_type": [NODE_TYPES[n["type"]] for n in nodes], "node_id_to_idx": index}}
