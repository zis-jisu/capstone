"""Source-grounded context helpers shared with evaluation."""
import re

def build_work_event_context(tasks, events):
    """Preserve source-grounded Event context for Task -> Work integration."""
    event_map = {e["event_id"]: e for e in events}
    context = []

    for task in tasks:
        task_event_ids = [x["event_id"] for x in task.get("events", [])]
        task_events = []

        for event_id in task_event_ids:
            e = event_map.get(event_id)
            if not e:
                continue
            task_events.append({
                "event_id": event_id,
                "source_id": e.get("source_id"),
                "source_channel": e.get("source_channel"),
                "source_timestamp": e.get("source_timestamp"),
                "source_thread_key": e.get("source_thread_key"),
                "subject": e.get("subject"),
                "action": e.get("action"),
                "event_type": e.get("event_type"),
                "status": e.get("status"),
                "prerequisite": e.get("prerequisite"),
                "constraint": e.get("constraint"),
                "note": e.get("note"),
                "actor": e.get("actor"),
                "recipient": e.get("recipient"),
                "related_people": e.get("related_people", []),
                "deadline": e.get("deadline"),
                "evidence": e.get("evidence")
            })

        context.append({
            "task_id": task["task_id"],
            "title": task.get("title"),
            "next_action": task.get("next_action"),
            "events": task_events
        })

    return context

def _msg_order(source_id):
    if not source_id:
        return -1
    m = re.search(r"(\d+)$", source_id)
    return int(m.group(1)) if m else -1

def derive_strong_work_links(tasks, event_context):
    """Derive only high-confidence Task links from existing Event evidence.

    This is deterministic and uses no extra LLM/API call. The goal is to
    stabilize Work grouping with explicit handoff/prerequisite evidence.
    """
    task_by_id = {t["task_id"]: t for t in tasks}
    ctx_by_id = {c["task_id"]: c for c in event_context}
    titles = {
        t["task_id"]: (t.get("title") or "").strip()
        for t in tasks
        if (t.get("title") or "").strip()
    }

    task_actor_ids = {}
    task_channels = {}
    task_thread_keys = {}
    task_first_order = {}
    for task_id, ctx in ctx_by_id.items():
        actors = set()
        channels = set()
        thread_keys = set()
        orders = []
        for e in ctx.get("events", []):
            actor = e.get("actor") or {}
            if actor.get("slack_id"):
                actors.add(actor["slack_id"])
            if e.get("source_channel"):
                channels.add(e["source_channel"])
            if e.get("source_thread_key"):
                thread_keys.add(e["source_thread_key"])
            order = _msg_order(e.get("source_id"))
            if order >= 0:
                orders.append(order)
        task_actor_ids[task_id] = actors
        task_channels[task_id] = channels
        task_thread_keys[task_id] = thread_keys
        task_first_order[task_id] = min(orders) if orders else 10**9

    links = []
    seen = set()

    def add_link(source, target, reason, evidence):
        if not source or not target or source == target:
            return
        key = (source, target, reason, evidence)
        if key in seen:
            return
        seen.add(key)
        links.append({
            "source_task_id": source,
            "target_task_id": target,
            "reason": reason,
            "evidence": evidence
        })

    # 1) Exact Task-title reference in prerequisite/evidence/next_action.
    for source_id, ctx in ctx_by_id.items():
        texts = []
        next_action = (task_by_id[source_id].get("next_action") or "").strip()
        if next_action:
            texts.append(("next_action", next_action))
        for e in ctx.get("events", []):
            for field in ("prerequisite", "evidence", "action"):
                value = (e.get(field) or "").strip()
                if value:
                    texts.append((field, value))
        for field, text in texts:
            for target_id, title in titles.items():
                if target_id != source_id and len(title) >= 4 and title in text:
                    # If current Task explicitly cites another Task title as a
                    # prerequisite/context, they are strongly linked.
                    add_link(target_id, source_id, f"explicit_{field}_task_reference", text)

    # 2) Explicit execution handoff only when both Tasks share the same
    # opaque Slack thread context. Across a global corpus, recurring people,
    # channels, or generic topic words are not strong enough for a deterministic
    # must-link because they can bridge unrelated projects.
    strong_assignment_terms = ("다음 업무", "후속 업무", "후속 작업", "이어가", "이어서 진행", "정리본 기준으로 이어")

    for source_id, ctx in ctx_by_id.items():
        source_threads = task_thread_keys.get(source_id, set())
        if not source_threads:
            continue

        for e in ctx.get("events", []):
            action = str(e.get("action") or "").strip()
            evidence = str(e.get("evidence") or "").strip()
            if not any(term in action for term in strong_assignment_terms):
                continue

            recipient = e.get("recipient") or {}
            rid = recipient.get("slack_id")
            if not rid:
                continue

            event_order = _msg_order(e.get("source_id"))
            candidates = [
                target_id for target_id, actors in task_actor_ids.items()
                if target_id != source_id
                and rid in actors
                and task_first_order.get(target_id, 10**9) > event_order
                and bool(source_threads & task_thread_keys.get(target_id, set()))
            ]
            if not candidates:
                continue

            target_id = min(candidates, key=lambda x: task_first_order[x])
            add_link(
                source_id,
                target_id,
                "explicit_assignment_same_thread",
                evidence or action
            )

    return links

def build_must_link_clusters(tasks, links):
    """Union connected Tasks into deterministic must-link Work candidates."""
    parent = {t["task_id"]: t["task_id"] for t in tasks}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for link in links:
        a = link["source_task_id"]
        b = link["target_task_id"]
        if a in parent and b in parent:
            union(a, b)

    groups = {}
    for task_id in parent:
        groups.setdefault(find(task_id), []).append(task_id)

    return [
        sorted(group)
        for group in groups.values()
        if len(group) > 1
    ]
