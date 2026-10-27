"""HTTP adapter for the existing Slack -> Event -> Task -> Work backend.

Run: uvicorn src.frontend_api:app --host 127.0.0.1 --port 8000
Requires: fastapi, uvicorn, MCP + backend API environment variables.
"""
import json
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.db import SupabaseStore, export_graph, to_db, TABLE_KEYS
from src.pipeline import run_pipeline
from src.slack.mcp_server import collect_context
from src import ml_bridge

from src.agent_chat import router as agent_chat_router

app = FastAPI(title="Capstone Slack Handover API", version="0.1.0")
app.include_router(agent_chat_router)
origins = [x.strip() for x in os.getenv("FRONTEND_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])
_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_active_job = None
_ROOT = Path(os.getenv("HANDOVER_OUTPUT_DIR", "handover_runs"))


class SyncRequest(BaseModel):
    person_id: str = Field(pattern=r"^U[A-Z0-9]+$", max_length=40)
    days: int = Field(default=14, ge=1, le=90)


def _authorize(authorization: str | None):
    secret = os.getenv("API_ACCESS_TOKEN", "")
    if not secret:
        raise HTTPException(503, "API_ACCESS_TOKEN is not configured")
    expected = "Bearer " + secret
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(401, "Unauthorized")


def _snapshot():
    return SupabaseStore().snapshot()


def _write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def work_views(snapshot):
    by_id = {t["task_id"]: t for t in snapshot["tasks"]}
    edges = snapshot["edges"]
    grouped = {}
    for e in edges:
        if e["relation"] == "HAS_TASK" and e["source_type"] == "Work":
            grouped.setdefault(e["source_id"], []).append(e["target_id"])
    return [{**w, "task_count": len(grouped.get(w["work_id"], [])),
             "task_ids": grouped.get(w["work_id"], [])} for w in snapshot["works"]]


def work_detail(snapshot, work_id):
    work = next((w for w in snapshot["works"] if w["work_id"] == work_id), None)
    if work is None:
        return None
    edges = snapshot["edges"]
    task_ids = {e["target_id"] for e in edges if e["relation"] == "HAS_TASK" and e["source_id"] == work_id}
    task_rows = [t for t in snapshot["tasks"] if t["task_id"] in task_ids]
    event_ids = {e["target_id"] for e in edges if e["relation"] == "HAS_EVENT" and e["source_id"] in task_ids}
    events = [e for e in snapshot["events"] if e["event_id"] in event_ids]
    events.sort(key=lambda e: e.get("slack_ts") or "")
    return {"work": work, "tasks": task_rows, "events": events,
            "relations": [e for e in edges if e["source_id"] in task_ids | {work_id} or e["target_id"] in task_ids],
            "persons": snapshot["persons"]}


@app.get("/api/health")
def health():
    ml = ml_bridge.configuration_status()
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat(),
            "ml_api": "configured" if ml["configured"] else "misconfigured",
            "ml_api_url": ml["base_url"]}


@app.get("/api/works")
def get_works(authorization: str | None = Header(default=None)):
    _authorize(authorization)
    return {"works": work_views(_snapshot())}


@app.get("/api/works/{work_id}")
def get_work(work_id: str, authorization: str | None = Header(default=None)):
    _authorize(authorization)
    data = work_detail(_snapshot(), work_id)
    if data is None:
        raise HTTPException(404, "Work not found")
    return data


@app.get("/api/persons")
def get_persons(authorization: str | None = Header(default=None)):
    _authorize(authorization)
    return {"persons": _snapshot()["persons"]}


def _run_sync(job_id, request):
    global _active_job
    job_dir = _ROOT / job_id
    try:
        _jobs[job_id]["stage"] = "slack_collection"
        raw = collect_context(request.person_id, request.days)
        _write(job_dir / "slack_raw.json", raw)
        if not raw["records"]:
            raise ValueError("No Slack messages matched this user and time range")
        store = SupabaseStore()
        before = store.snapshot()
        _write(job_dir / "db_before.json", before)
        _jobs[job_id]["stage"] = "event_task_work"
        result = run_pipeline(raw, snapshot=before, event_cache_dir=job_dir / "event_cache")
        _write(job_dir / "result.json", result)
        bundle, warnings = to_db(result, before)
        _write(job_dir / "bundle.json", bundle)
        _jobs[job_id]["stage"] = "db_save"
        store.save(bundle, before)
        after = store.snapshot()
        _jobs[job_id]["stage"] = "db_verification"
        for table, rows in bundle.items():
            keys = TABLE_KEYS[table].split(",")
            found = {tuple(row[k] for k in keys) for row in after[table]}
            for row in rows:
                if tuple(row[k] for k in keys) not in found:
                    raise RuntimeError("Missing DB row after save: " + table)
        _jobs[job_id]["stage"] = "graph_export"
        graph = export_graph(after)
        _write(job_dir / "graph.json", graph)
        _jobs[job_id].update(status="completed", stage="done", counts={
            "messages": len(raw["records"]), "events": len(result["events"]),
            "tasks": len(result["tasks"]), "works": len(result["works"]),
            "graph_nodes": graph["metadata"]["num_nodes"],
            "graph_edges": graph["metadata"]["num_edges"], "warnings": len(warnings)})
    except Exception as exc:
        # Do not expose provider errors, credentials, or raw Slack messages over HTTP.
        _jobs[job_id].update(status="failed", error_type=type(exc).__name__,
                              stage=_jobs[job_id]["stage"])
    finally:
        with _lock:
            _active_job = None


@app.post("/api/sync", status_code=202)
def start_sync(request: SyncRequest, authorization: str | None = Header(default=None)):
    global _active_job
    _authorize(authorization)
    with _lock:
        if _active_job is not None:
            raise HTTPException(409, "Another sync job is running")
        job_id = uuid4().hex
        _jobs[job_id] = {"job_id": job_id, "status": "running", "stage": "queued"}
        _active_job = job_id
    threading.Thread(target=_run_sync, args=(job_id, request), daemon=True).start()
    return _jobs[job_id]


@app.get("/api/sync/{job_id}")
def sync_status(job_id: str, authorization: str | None = Header(default=None)):
    _authorize(authorization)
    if job_id not in _jobs:
        raise HTTPException(404, "Job not found")
    return _jobs[job_id]
