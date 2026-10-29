from __future__ import annotations

import logging
import os
import json
import queue
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .config import Settings
from .graph import (
    direct_task_ids,
    normalize_graph,
    overlay_live_task_fields,
    resolve_person,
)
from .model import task_impact_scores
from .priority import PRIORITY_POLICY, rank_tasks
from .repository import fetch_graph
from .runtime import ModelRuntime
from .training import train_once


logger = logging.getLogger(__name__)


class TrainingRequest(BaseModel):
    trigger: str = Field(default="manual", pattern=r"^[a-z0-9_-]{1,40}$")
    snapshot_key: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9._:-]{1,80}$"
    )


class PriorityRequest(BaseModel):
    person_id: str | None = Field(default=None, min_length=1, examples=["U0C22C8M742"])
    person_ids: list[str] | None = Field(
        default=None,
        examples=[["U0C22C8M742", "U0C1M3Q1PRV"]],
    )
    receiver_person_id: str | None = Field(
        default=None,
        min_length=1,
        examples=["U0C20G9MRML"],
    )


class TrainingCoordinator:
    def __init__(self, settings: Settings, runtime: ModelRuntime):
        self.settings = settings
        self.runtime = runtime
        self.lock = threading.Lock()
        self.state: dict[str, Any] = {
            "status": "idle",
            "trigger": None,
            "current_epoch": 0,
            "total_epochs": settings.epochs,
            "progress_percent": 0.0,
            "loss": None,
            "updated_at": None,
            "error": None,
            "last_result": None,
        }

    def begin(self, trigger: str, snapshot_key: str) -> bool:
        with self.lock:
            if self.state["status"] in {"queued", "running"}:
                return False
            self.state = {
                "status": "running",
                "trigger": trigger,
                "training_snapshot_key": snapshot_key,
                "current_epoch": 0,
                "total_epochs": self.settings.epochs,
                "progress_percent": 0.0,
                "loss": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
                "last_result": self.state.get("last_result"),
            }
            return True

    def update_progress(self, epoch: int, epochs: int, loss: float) -> None:
        with self.lock:
            self.state.update(
                {
                    "status": "running",
                    "current_epoch": epoch,
                    "total_epochs": epochs,
                    "progress_percent": round(epoch / epochs * 100, 1),
                    "loss": loss,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

    def complete(self, trigger: str, result: dict[str, Any]) -> None:
        with self.lock:
            self.state = {
                "status": "completed",
                "trigger": trigger,
                "training_snapshot_key": result.get("training_snapshot_key"),
                "current_epoch": self.settings.epochs,
                "total_epochs": self.settings.epochs,
                "progress_percent": 100.0,
                "loss": result.get("final_loss"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
                "last_result": result,
            }

    def fail(self, trigger: str, error: Exception) -> None:
        with self.lock:
            self.state = {
                "status": "failed",
                "trigger": trigger,
                "training_snapshot_key": self.state.get("training_snapshot_key"),
                "current_epoch": self.state.get("current_epoch", 0),
                "total_epochs": self.state.get("total_epochs", self.settings.epochs),
                "progress_percent": self.state.get("progress_percent", 0.0),
                "loss": self.state.get("loss"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "error": f"{type(error).__name__}: {error}",
                "last_result": self.state.get("last_result"),
            }

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            state = dict(self.state)
        state.update(self.runtime.metadata())
        return state

def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    expected = request.app.state.settings.api_key
    if expected and x_api_key != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid API key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    runtime = ModelRuntime(settings)
    try:
        runtime.load_latest()
    except Exception:
        logger.exception("latest model could not be loaded; waiting for first training")
    coordinator = TrainingCoordinator(settings, runtime)
    app.state.settings = settings
    app.state.runtime = runtime
    app.state.coordinator = coordinator
    yield


app = FastAPI(
    title="Handover R-GAE API",
    version="4.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health(request: Request):
    metadata = request.app.state.runtime.metadata()
    return {
        "status": "ok" if metadata["model_loaded"] else "waiting_for_training",
        **metadata,
    }


@app.get("/v1/training", dependencies=[Depends(require_api_key)])
def training_status(request: Request):
    """Dashboard polling endpoint: status and latest successful training date."""
    refresh_error = None
    try:
        request.app.state.runtime.refresh_if_due()
    except Exception as error:
        # Status polling must still expose a failed training result even when
        # the latest model object cannot be loaded from Storage.
        logger.exception("latest model refresh failed during status polling")
        refresh_error = f"{type(error).__name__}: {error}"
    snapshot = request.app.state.coordinator.snapshot()
    if refresh_error:
        snapshot["model_refresh_error"] = refresh_error
    return snapshot


@app.post(
    "/v1/training",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_api_key)],
)
def start_training(request: Request, body: TrainingRequest):
    """Stream training progress so Railway keeps the serverless container awake."""
    coordinator: TrainingCoordinator = request.app.state.coordinator
    snapshot_key = body.snapshot_key or coordinator.settings.training_snapshot_key
    if not coordinator.begin(body.trigger, snapshot_key):
        raise HTTPException(status.HTTP_409_CONFLICT, "training is already running")

    events: queue.Queue[dict[str, Any]] = queue.Queue()

    def progress(epoch: int, epochs: int, loss: float) -> None:
        coordinator.update_progress(epoch, epochs, loss)
        if epoch == 1 or epoch % 10 == 0 or epoch == epochs:
            events.put(
                {
                    "status": "running",
                    "trigger": body.trigger,
                    "training_snapshot_key": snapshot_key,
                    "current_epoch": epoch,
                    "total_epochs": epochs,
                    "progress_percent": round(epoch / epochs * 100, 1),
                    "loss": loss,
                }
            )

    def work() -> None:
        try:
            result = train_once(
                coordinator.settings,
                coordinator.runtime,
                body.trigger,
                snapshot_key=snapshot_key,
                progress=progress,
            )
            coordinator.complete(body.trigger, result)
            events.put(result)
        except Exception as error:
            logger.exception("training failed")
            coordinator.fail(body.trigger, error)
            events.put(
                {
                    "status": "failed",
                    "trigger": body.trigger,
                    "training_snapshot_key": snapshot_key,
                    "error": f"{type(error).__name__}: {error}",
                }
            )

    threading.Thread(target=work, name="rgae-training", daemon=True).start()

    def stream():
        yield json.dumps(
            {"accepted": True, "status": "running", "trigger": body.trigger,
             "training_snapshot_key": snapshot_key}
        ) + "\n"
        while True:
            try:
                event = events.get(timeout=20)
            except queue.Empty:
                event = {"status": "running", "heartbeat": True}
            yield json.dumps(event) + "\n"
            if event.get("status") in {"completed", "failed"}:
                break

    return StreamingResponse(
        stream(),
        status_code=status.HTTP_202_ACCEPTED,
        media_type="application/x-ndjson",
    )


@app.post("/v1/priorities", dependencies=[Depends(require_api_key)])
def priorities(request: Request, body: PriorityRequest):
    runtime: ModelRuntime = request.app.state.runtime
    try:
        source_ids = list(dict.fromkeys(
            ([body.person_id] if body.person_id else []) + (body.person_ids or [])
        ))
        if not source_ids:
            raise ValueError("person_id or person_ids must contain at least one source person")
        if len(source_ids) > 20:
            raise ValueError("at most 20 source people can be ranked together")
        runtime.refresh_if_due()
        trained_graph, prepared, model, seed, record = runtime.snapshot()
        live_graph = normalize_graph(fetch_graph(request.app.state.settings))
        graph = overlay_live_task_fields(trained_graph, live_graph)
        source_people = [resolve_person(graph, person_id) for person_id in source_ids]
        receiver = (
            resolve_person(graph, body.receiver_person_id)
            if body.receiver_person_id
            else None
        )
        if receiver and receiver["id"] in source_ids:
            raise ValueError("receiver_person_id must differ from source person_ids")
        candidates = direct_task_ids(graph, source_ids)
        if not candidates:
            return {
                "person_id": source_ids[0] if len(source_ids) == 1 else None,
                "person_name": source_people[0].get("name") if len(source_ids) == 1 else None,
                "source_people": [
                    {"person_id": person["id"], "person_name": person.get("name")}
                    for person in source_people
                ],
                "receiver": (
                    {"person_id": receiver["id"], "person_name": receiver.get("name")}
                    if receiver
                    else None
                ),
                "candidate_scope": "direct_1hop_active_tasks",
                "priority_policy": PRIORITY_POLICY,
                "model_trained_at": record["trained_at"],
                "rankings": {},
            }

        impact, _removed_edges = task_impact_scores(
            model,
            prepared,
            source_ids,
            runtime.device,
            seed,
        )
        missing = [task_id for task_id in candidates if task_id not in impact]
        if missing:
            raise RuntimeError(f"model did not score candidate tasks: {missing}")
        rankings = rank_tasks(graph, source_ids, candidates, impact)
    except KeyError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
    except Exception as error:
        logger.exception("priority calculation failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Supabase or model request failed: {error}",
        ) from error

    return {
        "person_id": source_ids[0] if len(source_ids) == 1 else None,
        "person_name": source_people[0].get("name") if len(source_ids) == 1 else None,
        "source_people": [
            {"person_id": person["id"], "person_name": person.get("name")}
            for person in source_people
        ],
        "receiver": (
            {"person_id": receiver["id"], "person_name": receiver.get("name")}
            if receiver
            else None
        ),
        "candidate_scope": "direct_1hop_active_tasks",
        "priority_policy": PRIORITY_POLICY,
        "model_trained_at": record["trained_at"],
        "rankings": {row["task_id"]: row for row in rankings},
    }


def configure_cors(application: FastAPI) -> None:
    origins = [
        item.strip()
        for item in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
        if item.strip()
    ]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key"],
    )


configure_cors(app)

