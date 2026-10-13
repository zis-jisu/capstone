from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import Settings
from .graph import (
    normalize_graph,
    overlay_live_task_fields,
    resolve_person,
    two_hop_task_ids,
)
from .model import task_impact_scores
from .priority import rank_tasks
from .repository import fetch_graph
from .runtime import ModelRuntime
from .training import train_once


logger = logging.getLogger(__name__)


class TrainingRequest(BaseModel):
    trigger: str = Field(default="manual", pattern=r"^[a-z0-9_-]{1,40}$")


class PriorityRequest(BaseModel):
    person_id: str = Field(min_length=1, examples=["U0C22C8M742"])


class TrainingCoordinator:
    def __init__(self, settings: Settings, runtime: ModelRuntime):
        self.settings = settings
        self.runtime = runtime
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rgae-training")
        self.lock = threading.Lock()
        self.state: dict[str, Any] = {
            "status": "idle",
            "trigger": None,
            "error": None,
            "last_result": None,
        }

    def start(self, trigger: str) -> bool:
        with self.lock:
            if self.state["status"] in {"queued", "running"}:
                return False
            self.state = {
                "status": "queued",
                "trigger": trigger,
                "error": None,
                "last_result": self.state.get("last_result"),
            }

        def work() -> None:
            with self.lock:
                self.state["status"] = "running"
            try:
                result = train_once(self.settings, self.runtime, trigger)
                with self.lock:
                    self.state = {
                        "status": "completed",
                        "trigger": trigger,
                        "error": None,
                        "last_result": result,
                    }
            except Exception as error:
                logger.exception("training failed")
                with self.lock:
                    self.state = {
                        "status": "failed",
                        "trigger": trigger,
                        "error": f"{type(error).__name__}: {error}",
                        "last_result": self.state.get("last_result"),
                    }

        self.executor.submit(work)
        return True

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            state = dict(self.state)
        state.update(self.runtime.metadata())
        return state

    def close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=False)


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
    coordinator.close()


app = FastAPI(
    title="Handover R-GAE API",
    version="3.0.0",
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
    request.app.state.runtime.refresh_if_due()
    return request.app.state.coordinator.snapshot()


@app.post(
    "/v1/training",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_api_key)],
)
def start_training(request: Request, body: TrainingRequest):
    """Fetch the latest Supabase RPC graph and train in the background."""
    if not request.app.state.coordinator.start(body.trigger):
        raise HTTPException(status.HTTP_409_CONFLICT, "training is already running")
    return {"accepted": True, "status": "queued", "trigger": body.trigger}


@app.post("/v1/priorities", dependencies=[Depends(require_api_key)])
def priorities(request: Request, body: PriorityRequest):
    runtime: ModelRuntime = request.app.state.runtime
    try:
        runtime.refresh_if_due()
        trained_graph, prepared, model, seed, record = runtime.snapshot()
        live_graph = normalize_graph(fetch_graph(request.app.state.settings))
        graph = overlay_live_task_fields(trained_graph, live_graph)
        person = resolve_person(graph, body.person_id)
        candidates = two_hop_task_ids(graph, body.person_id, hops=2)
        if not candidates:
            return {
                "person_id": body.person_id,
                "person_name": person.get("name"),
                "model_trained_at": record["trained_at"],
                "rankings": {},
            }

        impact, _removed_edges = task_impact_scores(
            model,
            prepared,
            body.person_id,
            runtime.device,
            seed,
        )
        missing = [task_id for task_id in candidates if task_id not in impact]
        if missing:
            raise RuntimeError(f"model did not score candidate tasks: {missing}")
        rankings = rank_tasks(graph, body.person_id, candidates, impact)
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
        "person_id": body.person_id,
        "person_name": person.get("name"),
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

