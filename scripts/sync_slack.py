"""Prepare a reviewable DB sync, then apply that exact saved plan.

Usage: python scripts/sync_slack.py --input messages.json --out handover_runs/run.json
       python scripts/sync_slack.py --apply-plan handover_runs/run.json
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.db import SupabaseStore, to_db, export_graph
from src.pipeline import run_pipeline


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(snapshot):
    # Table response ordering must not affect the stale-plan check.
    normalized = {table: sorted(rows, key=lambda r: json.dumps(r, sort_keys=True))
                  for table, rows in snapshot.items()}
    return hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def identity_conflicts(bundle, before):
    conflicts = []
    for person in bundle["persons"]:
        for old in before.get("persons", []):
            if old["name"] == person["name"] and old["person_id"] != person["person_id"]:
                conflicts.append({"name": person["name"], "existing_id": old["person_id"],
                                  "incoming_id": person["person_id"]})
    return conflicts


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", help="Slack message JSON including people mapping")
    ap.add_argument("--result", help="Already extracted service result; no LLM call")
    ap.add_argument("--snapshot", help="Saved DB snapshot for offline preparation")
    ap.add_argument("--prior-result", help="Previous run plan (preserves status history)")
    ap.add_argument("--event-cache-dir", default="handover_runs/event_cache", help="Cache verified Event extraction for safe retries")
    ap.add_argument("--out", default="handover_runs/run.json")
    ap.add_argument("--apply-plan", help="Apply this saved plan; never rerun LLM")
    args = ap.parse_args()
    if args.apply_plan:
        if any((args.input, args.result, args.snapshot, args.prior_result)):
            ap.error("--apply-plan cannot be combined with preparation inputs")
        plan = read(args.apply_plan)
        store = SupabaseStore()
        if plan.get("project_url") != store.url:
            raise ValueError("Plan was prepared for a different Supabase project.")
        if plan.get("identity_conflicts"):
            raise ValueError("Resolve person ID mapping with the DB owner before applying.")
        before = store.snapshot()
        if digest(before) != plan["before_digest"]:
            raise ValueError("DB changed since preparation. Prepare against a fresh snapshot.")
        # Revalidate the saved result, don't trust edited plan row arrays.
        bundle, _ = to_db(plan["result"], before)
        if bundle != plan["bundle"]:
            raise ValueError("Plan bundle differs from its source result.")
        write(Path(args.apply_plan).with_suffix(".before.json"), before)
        store.save(bundle, before)
        # Original Slack text is kept separately from Graph node/edge exports.
        # Upsert only selected fields, preserving existing work/task associations.
        store.save_messages(plan["result"].get("messages", []),
                            plan["result"].get("people", []))
        after = store.snapshot()
        # Verify every intended row after writing (ignore server-created fields).
        from src.db import TABLE_KEYS
        for table, rows in bundle.items():
            keys = TABLE_KEYS[table].split(",")
            saved = {tuple(r[k] for k in keys): r for r in after[table]}
            for row in rows:
                actual = saved.get(tuple(row[k] for k in keys))
                if not actual:
                    raise RuntimeError(f"Post-write verification failed for {table}.")
                for key, value in row.items():
                    actual_value = actual.get(key)
                    if key in {"due_at", "deadline_at", "updated_at"} and value and actual_value:
                        from datetime import datetime
                        equal = datetime.fromisoformat(value.replace("Z", "+00:00")) == datetime.fromisoformat(actual_value.replace("Z", "+00:00"))
                    else:
                        equal = actual_value == value
                    if not equal:
                        raise RuntimeError(f"Post-write value mismatch: {table}.{key}")
        graph = export_graph(after)
        graph_path = Path(args.apply_plan).with_suffix(".graph.json")
        write(graph_path, graph)
        plan["applied"] = True
        write(args.apply_plan, plan)
        print(f"Verified DB save. Graph: {graph_path}")
        return
    if bool(args.input) == bool(args.result):
        ap.error("Specify exactly one of --input or --result")
    if args.snapshot:
        before = read(args.snapshot)
        project_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    else:
        store = SupabaseStore()
        before, project_url = store.snapshot(), store.url
    prior = read(args.prior_result) if args.prior_result else {}
    result = read(args.result) if args.result else run_pipeline(
        read(args.input), snapshot=before, prior_result=prior.get("result", prior),
        event_cache_dir=args.event_cache_dir)
    bundle, warnings = to_db(result, before)
    conflicts = identity_conflicts(bundle, before)
    plan = {"project_url": project_url, "before_digest": digest(before), "result": result,
            "bundle": bundle, "warnings": warnings, "identity_conflicts": conflicts, "applied": False,
            "schema_gaps": ["Full Slack messages and Task status_history retained in this plan; DB has no dedicated tables."]}
    write(args.out, plan)
    print(f"Saved plan: {args.out}")
    print("Rows: " + ", ".join(f"{k}={len(v)}" for k, v in bundle.items()))
    print(f"Warnings: {len(warnings)}; identity conflicts: {len(conflicts)}")
    if conflicts:
        print("Apply blocked: existing person IDs differ from supplied Slack IDs.")
    print("DB unchanged. Apply the same plan with --apply-plan after resolving conflicts.")


if __name__ == "__main__":
    main()
