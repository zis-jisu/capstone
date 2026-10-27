"""Read-only Task -> Event -> original Slack message retrieval.

Call only after the API has authenticated the user and authorized the task.
No full-table snapshot and no database mutations.
"""
from src.db import SupabaseStore


def retrieve_task_evidence(task_id: str, store=None, *, limit=30):
    if not task_id or not isinstance(task_id, str):
        raise ValueError("task_id required")
    if not (1 <= limit <= 100):
        raise ValueError("limit must be between 1 and 100")
    store = store or SupabaseStore()
    tasks = store.request("tasks", params={"select": "*", "task_id": "eq." + task_id, "limit": 1})
    if not tasks:
        return {"task": None, "works": [], "events": [], "sources": []}

    links = store.request("edges", params={
        "select": "source_id,target_id,relation",
        "source_id": "eq." + task_id, "relation": "eq.HAS_EVENT",
        "limit": limit,
    })
    event_ids = list(dict.fromkeys(edge["target_id"] for edge in links))
    events = (store.request("events", params={
        "select": "*", "event_id": "in.(" + ",".join(event_ids) + ")",
        "limit": limit,
    }) if event_ids else [])
    events.sort(key=lambda event: event.get("slack_ts") or "")

    parents = store.request("edges", params={
        "select": "source_id,target_id,relation",
        "target_id": "eq." + task_id, "relation": "eq.HAS_TASK",
        "limit": limit,
    })
    work_ids = list(dict.fromkeys(edge["source_id"] for edge in parents))
    works = (store.request("works", params={
        "select": "*", "work_id": "in.(" + ",".join(work_ids) + ")",
        "limit": limit,
    }) if work_ids else [])

    # Event.source_id is the Slack message_id written by src.db.save_messages.
    source_ids = list(dict.fromkeys(
        event["source_id"] for event in events if event.get("source_id")
    ))
    raw = (store.request("slack_messages", params={
        "select": "message_id,author_id,author_name,channel,slack_ts,text,reference_urls",
        "message_id": "in.(" + ",".join(source_ids) + ")",
        "limit": limit,
    }) if source_ids else [])
    by_id = {message["message_id"]: message for message in raw}
    sources = []
    for event in events:
        message = by_id.get(event.get("source_id"))
        sources.append({
            "event_id": event["event_id"],
            "message_id": event.get("source_id"),
            "slack_ts": event.get("slack_ts"),
            "event": event,
            "message": message,
            "raw_message_found": message is not None,
        })
    return {"task": tasks[0], "works": works, "events": events, "sources": sources}
