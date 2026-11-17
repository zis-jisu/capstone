"""On-demand racing-channel Event-only demo sync, isolated from existing Work graphs."""
from datetime import datetime, timezone
from src.db import SupabaseStore, to_db
from src.pipeline import normalize_messages, assign_event_ids, prompt
from src.luna_api import call_structured
from src.schemas import EVENT_SCHEMA
from src.deadlines import message_time, normalize_deadline


def sync_racing_events(raw, store=None):
    store = store or SupabaseStore()
    records = raw.get("records", [])
    messages = normalize_messages(raw)
    people = raw.get("people", [])
    names = {p["slack_id"]: p["name"] for p in people}
    if len(names) != len(people) or any(m["slack_id"] not in names for m in messages):
        raise ValueError("Missing Slack user mapping for racing channel")
    cid = raw["channel_id"]
    if any(m["channel"] != cid for m in messages):
        raise ValueError("Racing channel collector returned another channel")
    store.preflight_raw_message_schema()
    previous = {}
    offset = 0
    while True:
        page = store.request("slack_messages", params={
            "select": "message_id,text,author_id", "conversation_id": "eq." + cid,
            "order": "message_id.asc", "limit": 500, "offset": offset})
        previous.update({p["message_id"]: p for p in page})
        if len(page) < 500:
            break
        offset += len(page)
    changed = [m for m in messages if m["source_id"] not in previous or
               previous[m["source_id"]].get("text") != m["raw_text"] or
               previous[m["source_id"]].get("author_id") != m["slack_id"]]
    if not changed:
        return {"channel": raw.get("channel_name", cid), "messages": len(messages),
                "changed_messages": 0, "events": 0, "saved": True}
    before = store.snapshot()
    registered = {p["person_id"]: p for p in before["persons"]}
    for p in people:
        registered.setdefault(p["slack_id"], {"person_id": p["slack_id"],
                          "name": p["name"], "aliases": []})
    # Persist identities before their FK-referencing messages and Events.
    new_people = [registered[p["slack_id"]] for p in people if p["slack_id"] not in
                  {old["person_id"] for old in before["persons"]}]
    if new_people:
        store.upsert("persons", new_people)
    events = []
    for m in changed:
        payload = {"message": {"source_id": m["source_id"], "slack_id": m["slack_id"],
                    "timestamp": m["timestamp"], "timestamp_kst": message_time(m["timestamp"]).isoformat(),
                    "channel": cid, "text": m["raw_text"]}, "people": people}
        for attempt in range(3):
            result, _ = call_structured(system_prompt=prompt("event_extraction.md"),
                            user_payload=payload, json_schema=EVENT_SCHEMA)
            extracted = result["events"]
            invalid = [{"field": "evidence", "value": e.get("evidence")} for e in extracted
                       if not e.get("evidence") or e["evidence"] not in m["raw_text"]]
            invalid += [{"field": "deadline.text", "value": (e.get("deadline") or {}).get("text")}
                        for e in extracted if (e.get("deadline") or {}).get("text") and
                        e["deadline"]["text"] not in m["raw_text"]]
            if not invalid:
                break
            if attempt == 2:
                raise ValueError("Racing Event evidence validation failed")
            payload["validation_feedback"] = {"instruction":
                "Copy evidence and deadline.text verbatim from the message; do not paraphrase",
                "invalid_fields": invalid}
        for e in extracted:
            e["source_id"] = m["source_id"]
            e["deadline"] = normalize_deadline(e.get("deadline"), m["timestamp"])
            e.update({"speaker_id": m["slack_id"], "speaker": names[m["slack_id"]],
                      "slack_ts": m["timestamp"], "conversation_id": cid,
                      "conversation_type": "channel", "parent_ts": m["parent_ts"],
                      "reference_urls": m["reference_urls"]})
        prior = [e for e in before["events"] if e["source_id"] == m["source_id"]]
        assign_event_ids(extracted, prior)
        events.extend(extracted)
    result = {"people": people, "messages": changed, "events": events,
              "tasks": [], "works": [], "processed_at": datetime.now(timezone.utc).isoformat()}
    bundle, _ = to_db(result, before)
    if bundle["events"]:
        store.upsert("events", bundle["events"])
    if bundle["edges"]:
        store.upsert("edges", bundle["edges"])
    store.save_messages(changed, people)
    saved_ids = {e["event_id"] for e in store.fetch("events")}
    if not {e["event_id"] for e in bundle["events"]} <= saved_ids:
        raise RuntimeError("Racing Event write verification failed")
    page = store.request("slack_messages", params={"select": "message_id",
            "conversation_id": "eq." + cid, "limit": 5000})
    ids = {row["message_id"] for row in page}
    if not {m["source_id"] for m in changed} <= ids:
        raise RuntimeError("Racing raw message write verification failed")
    return {"channel": raw.get("channel_name", cid), "messages": len(messages),
            "changed_messages": len(changed), "events": len(events), "saved": True}
