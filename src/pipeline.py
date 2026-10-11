"""Slack -> Event -> Task -> Work service entry point, independent of Gold data."""
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src.deadlines import message_time, normalize_deadline
from src.luna_api import call_structured
from src.pipeline_context import (build_work_event_context, derive_strong_work_links,
                                  build_must_link_clusters)
from src.schemas import EVENT_SCHEMA, TASK_SCHEMA, WORK_SCHEMA

ROOT = Path(__file__).resolve().parents[1]


def prompt(name):
    return (ROOT / "prompts" / name).read_text(encoding="utf-8")


def normalize_messages(data):
    """Accept collector records or the existing experiment message envelope."""
    messages = []
    for m in data.get("records", data.get("messages", [])):
        sid = m.get("source_id") or m.get("id")
        ts = m.get("slack_ts") or m.get("timestamp")
        if not sid or not ts:
            raise ValueError("Every message requires a source ID and source timestamp.")
        message_time(ts)  # reject naive time rather than assuming the host timezone
        raw = m.get("raw_text", m.get("text", ""))
        channel = m.get("conversation_id") or m.get("channel")
        author = m.get("slack_author_id") or m.get("author_id")
        if not channel or not author:
            raise ValueError("Every message requires a channel and Slack author ID.")
        links = m.get("reference_urls", []) or []
        links = list(dict.fromkeys(links + re.findall(r"https?://[^\s<>|]+", raw)))
        messages.append({"source_id": sid, "timestamp": ts, "slack_id": author,
                         "channel": channel, "conversation_type": m.get("conversation_type", "unknown"),
                         "parent_ts": m.get("parent_ts"), "edited": m.get("edited"),
                         "thread_key": m.get("thread_key") or (f"{channel}:{m['parent_ts']}" if m.get("parent_ts") else None),
                         "raw_text": raw, "reference_urls": links})
    ids = [m["source_id"] for m in messages]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate source message IDs.")
    return sorted(messages, key=lambda m: message_time(m["timestamp"]))


def existing_context(snapshot):
    people = {p["person_id"]: {"slack_id": p["person_id"], "name": p["name"]}
              for p in snapshot.get("persons", [])}
    tasks = {t["task_id"]: {**t, "deadline": {"text": t.get("deadline_text"), "at": t.get("deadline_at")},
             "events": [], "participants": [], "task_links": [], "status_history": []}
             for t in snapshot.get("tasks", [])}
    works = {w["work_id"]: {**w, "tasks": []} for w in snapshot.get("works", [])}
    for edge in snapshot.get("edges", []):
        src, rel, dst = edge["source_id"], edge["relation"], edge["target_id"]
        if rel == "HAS_EVENT" and src in tasks:
            tasks[src]["events"].append({"event_id": dst, "role": "core"})
        elif rel == "HAS_TASK" and src in works:
            works[src]["tasks"].append({"task_id": dst, "role": "core"})
        elif edge["source_type"] == "Person" and edge["target_type"] == "Task" and dst in tasks and src in people:
            tasks[dst]["participants"].append({**people[src], "roles": [rel.lower()],
                                               "event_ids": edge.get("evidence_event_ids", [])})
    return list(tasks.values()), list(works.values())


def assign_event_ids(events, previous):
    """Keep IDs for unchanged facts and unambiguous single-fact edits.

    Ambiguous edits fail closed; order changes must never silently swap IDs.
    Removing a fact requires a future explicit retirement workflow.
    """
    remaining = list(previous)
    pending = []
    for e in events:
        matches = [old for old in remaining if old.get("evidence") == e.get("evidence")
                   and old.get("event_type") == e.get("event_type")]
        if len(matches) == 1:
            e["event_id"] = matches[0]["event_id"]
            remaining.remove(matches[0])
        else:
            pending.append(e)
    for e in list(pending):
        matches = [old for old in remaining if old.get("subject") == e.get("subject")
                   and old.get("action") == e.get("action") and old.get("event_type") == e.get("event_type")]
        if len(matches) == 1:
            e["event_id"] = matches[0]["event_id"]
            remaining.remove(matches[0]); pending.remove(e)
    if len(remaining) == len(pending) == 1:
        pending.pop()["event_id"] = remaining.pop()["event_id"]
    if remaining:
        raise ValueError("Edited message has ambiguous or removed facts; reconcile Event IDs before saving.")
    for e in pending:
        e["event_id"] = "EVENT-" + uuid4().hex


def assign_ids(items, key, existing):
    seen = set()
    allowed = {x[key] for x in existing}
    for item in items:
        value = item.get(key)
        if value and value not in allowed:
            raise ValueError(f"LLM invented an existing {key}.")
        item[key] = value or key.removesuffix("_id").upper() + "-" + uuid4().hex
        if item[key] in seen:
            raise ValueError(f"Duplicate {key} in output.")
        seen.add(item[key])


def run_pipeline(data, *, snapshot=None, prior_result=None, call=call_structured, event_cache_dir=None):
    snapshot = snapshot or {}
    prior_result = prior_result or {}
    messages = normalize_messages(data)
    people = data.get("people", [])
    people_map = {p["slack_id"]: p for p in people if p.get("slack_id")}
    if len(people_map) != len(people) or any(not p.get("name") for p in people):
        raise ValueError("Supply unique Slack person IDs and display names.")
    for m in messages:
        if m["slack_id"] not in people_map:
            raise ValueError("Message author is missing from the supplied people mapping.")
    events = []
    for m in messages:
        payload = {"message": {"source_id": m["source_id"], "slack_id": m["slack_id"],
                    "timestamp": m["timestamp"], "timestamp_kst": message_time(m["timestamp"]).isoformat(),
                    "channel": m["channel"], "text": m["raw_text"]}, "people": people}
        # Cache only fully verified model Event output. A resumed run never
        # silently accepts an invalid quote or stale message content.
        cache_file = None
        cached_events = None
        if event_cache_dir is not None:
            cache_folder = Path(event_cache_dir)
            cache_folder.mkdir(parents=True, exist_ok=True)
            fingerprint = hashlib.sha256(json.dumps(
                {"message": payload["message"], "people": people,
                 "prompt": prompt("event_extraction.md")},
                sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            cache_file = cache_folder / (fingerprint + ".json")
            if cache_file.exists():
                cached_events = json.loads(cache_file.read_text(encoding="utf-8"))["events"]
        retry_payload = payload
        for attempt in range(3):
            if cached_events is not None:
                extracted = copy.deepcopy(cached_events)
            else:
                result, _ = call(system_prompt=prompt("event_extraction.md"),
                                 user_payload=retry_payload, json_schema=EVENT_SCHEMA)
                extracted = result["events"]
            invalid = []
            for index, e in enumerate(extracted):
                evidence = e.get("evidence")
                deadline_text = (e.get("deadline") or {}).get("text")
                if not evidence or evidence not in m["raw_text"]:
                    invalid.append({"event_index": index, "field": "evidence", "invalid_value": evidence})
                if deadline_text and deadline_text not in m["raw_text"]:
                    invalid.append({"event_index": index, "field": "deadline.text", "invalid_value": deadline_text})
            if not invalid:
                if cache_file is not None and cached_events is None:
                    tmp = cache_file.with_suffix(".tmp")
                    tmp.write_text(json.dumps({"events": extracted}, ensure_ascii=False),
                                   encoding="utf-8")
                    tmp.replace(cache_file)
                break
            if cached_events is not None:
                raise ValueError(f"Invalid cached Event output for {m['source_id']}: {invalid}")
            fields = ", ".join(sorted({issue["field"] for issue in invalid}))
            if attempt == 2:
                raise ValueError(f"Slack message {m['source_id']}: invalid {fields} after 3 attempts.")
            # Keep the original source message unchanged. Give the model exact
            # field-level feedback instead of rerunning the identical prompt.
            retry_payload = {**payload, "validation_feedback": {
                "instruction": "Regenerate events for this same Slack message. Every evidence must be an EXACT contiguous substring copied from message.text, with identical Slack markup, spaces, line breaks and punctuation. Never paraphrase. deadline.text must also be copied verbatim. If there is no work fact, return an empty events list.",
                "invalid_fields": invalid
            }}
            print(f"Retry Event extraction: {m['source_id']} ({fields}, attempt {attempt + 2}/3)",
                  flush=True)
        print(f"Event extraction {'cached' if cached_events is not None else 'completed'}: "
              f"{m['source_id']} ({len(extracted)} events)", flush=True)
        previous = [e for e in snapshot.get("events", []) if e["source_id"] == m["source_id"]]
        for e in extracted:
            e["source_id"] = m["source_id"]
            e["deadline"] = normalize_deadline(e.get("deadline"), m["timestamp"])
            e.update({"speaker_id": m["slack_id"], "speaker": people_map[m["slack_id"]]["name"],
                      "slack_ts": m["timestamp"], "conversation_id": m["channel"],
                      "conversation_type": m["conversation_type"], "parent_ts": m["parent_ts"],
                      "source_channel": m["channel"], "source_timestamp": m["timestamp"],
                      "source_thread_key": m["thread_key"], "reference_urls": m["reference_urls"]})
        assign_event_ids(extracted, previous)
        events.extend(extracted)
    old_tasks, old_works = existing_context(snapshot)
    # The current DB has no status_history column. Restore audit history from the
    # previous full run result until a database history table is added.
    history = copy.deepcopy(prior_result.get("status_history_by_task", {}))
    history.update({t["task_id"]: t.get("status_history", []) for t in prior_result.get("tasks", [])})
    for t in old_tasks:
        t["status_history"] = history.get(t["task_id"], [])
    processed_at = datetime.now(timezone.utc).isoformat()
    if not events:
        return {"people": people, "messages": messages, "events": [], "tasks": [], "works": [],
                "processed_at": processed_at, "status_history_by_task": history}
    # Retry only Task integration when Event membership is missing or duplicated.
    # Check BEFORE assign_ids so failed attempts never consume generated IDs.
    event_map = {e["event_id"]: e for e in events}
    known_events = set(event_map) | {e["event_id"] for e in snapshot.get("events", [])}
    task_payload = {"new_events": events, "existing_tasks": old_tasks, "people": people}
    for attempt in range(3):
        task_result, _ = call(system_prompt=prompt("event_to_task.md"),
            user_payload=task_payload, json_schema=TASK_SCHEMA, max_output_tokens=16000)
        tasks = task_result["tasks"]
        memberships = [item["event_id"] for task in tasks for item in task["events"]]
        from collections import Counter
        counts = Counter(x for x in memberships if x in event_map)
        missing = sorted(set(event_map) - set(counts))
        duplicated = sorted(x for x, n in counts.items() if n != 1)
        unknown = sorted(set(memberships) - known_events)
        if not (missing or duplicated or unknown):
            break
        if attempt == 2:
            raise ValueError(f"Task integration invalid after 3 attempts: missing={missing}, duplicated={duplicated}, unknown={unknown}")
        print(f"Retry Task integration (attempt {attempt + 2}/3): missing={len(missing)}, duplicated={len(duplicated)}, unknown={len(unknown)}", flush=True)
        task_payload = {**task_payload, "previous_invalid_tasks": tasks,
            "validation_feedback": {"instruction": "Regenerate the entire Task list. Each new Event must appear in exactly one Task; never invent Event IDs.",
                                    "missing_event_ids": missing, "duplicated_event_ids": duplicated,
                                    "unknown_event_ids": unknown}}
    assign_ids(tasks, "task_id", old_tasks)
    old_map = {t["task_id"]: t for t in old_tasks}
    event_map = {e["event_id"]: e for e in events}
    known_events = set(event_map) | {e["event_id"] for e in snapshot.get("events", [])}
    coverage = []
    for t in tasks:
        tids = [x["event_id"] for x in t["events"]]
        if any(i not in known_events for i in tids):
            raise ValueError("Task references an invented Event.")
        coverage.extend(i for i in tids if i in event_map)
        old = old_map.get(t["task_id"])
        t["status_history"] = copy.deepcopy(old.get("status_history", [])) if old else []
        if old and old["status"] != t["status"]:
            t["status_history"].append({"from": old["status"], "to": t["status"], "changed_at": processed_at})
        # A merged existing task must preserve its unchanged event memberships.
        if old:
            referenced = set(tids)
            t["events"].extend(x for x in old["events"] if x["event_id"] not in referenced)
        d = t.get("deadline") or {}
        sources = [event_map[i] for i in tids if i in event_map
                   and event_map[i].get("deadline", {}).get("text") == d.get("text")]
        if sources:
            resolved = {e["deadline"].get("at") for e in sources}
            if len(resolved) != 1:
                raise ValueError("Task deadline matches conflicting Event deadlines.")
            t["deadline"] = copy.deepcopy(sources[0]["deadline"])
        elif old and d.get("text") == old["deadline"].get("text"):
            t["deadline"] = copy.deepcopy(old["deadline"])
        elif d.get("text"):
            raise ValueError("Task deadline has no source-grounded Event or existing deadline.")
        else:
            t["deadline"] = {"text": None, "at": None}
    if set(coverage) != set(event_map) or len(coverage) != len(set(coverage)):
        raise ValueError("Each new Event must belong to exactly one Task.")
    context = build_work_event_context(tasks, events)
    links = derive_strong_work_links(tasks, context)
    clusters = build_must_link_clusters(tasks, links)
    work_result, _ = call(system_prompt=prompt("task_to_work.md"),
        user_payload={"tasks": tasks, "event_context": context, "derived_strong_links": links,
                      "must_link_clusters": clusters, "existing_works": old_works},
        json_schema=WORK_SCHEMA, max_output_tokens=12000)
    works = work_result["works"]
    assign_ids(works, "work_id", old_works)
    task_ids = {t["task_id"] for t in tasks}
    old_task_ids = {t["task_id"] for t in old_tasks}
    coverage = []
    old_work_map = {w["work_id"]: w for w in old_works}
    for w in works:
        ids = [t["task_id"] for t in w["tasks"]]
        if any(i not in task_ids | old_task_ids for i in ids):
            raise ValueError("Work references an invented Task.")
        coverage.extend(i for i in ids if i in task_ids)
        if w["work_id"] in old_work_map:
            w["tasks"].extend(t for t in old_work_map[w["work_id"]]["tasks"]
                              if t["task_id"] not in set(ids) and t["task_id"] not in task_ids)
    if set(coverage) != task_ids or len(coverage) != len(set(coverage)):
        raise ValueError("Each updated Task must belong to exactly one Work.")
    history.update({t["task_id"]: t["status_history"] for t in tasks})
    return {"people": people, "messages": messages, "events": events, "tasks": tasks, "works": works,
            "processed_at": processed_at, "derived_strong_links": links, "status_history_by_task": history}
