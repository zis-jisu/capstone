from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import torch

from .config import Settings
from .graph import graph_digest, normalize_graph
from .model import build_model, prepare_graph, resolve_device, set_seed, train_model
from .repository import fetch_graph, upload_model

if TYPE_CHECKING:
    from .runtime import ModelRuntime


def train_once(
    settings: Settings,
    runtime: "ModelRuntime | None" = None,
    trigger: str = "manual",
    progress: Callable[[int, int, float], None] | None = None,
) -> dict[str, Any]:
    graph = normalize_graph(fetch_graph(settings))
    if not graph["nodes"] or not graph["edges"]:
        raise RuntimeError("Supabase graph is empty; mock data must be inserted first")

    digest = graph_digest(graph)
    set_seed(settings.seed)
    device = resolve_device(settings.device)
    prepared = prepare_graph(graph, settings.seed)
    model = build_model(prepared).to(device)
    final_loss = train_model(
        model,
        prepared,
        device,
        settings.epochs,
        settings.seed,
        progress=progress,
    )
    trained_at = datetime.now(timezone.utc).isoformat()
    artifact = {
        "format_version": 3,
        "model_state_dict": model.cpu().state_dict(),
        "graph": graph,
        "graph_sha256": digest,
        "seed": settings.seed,
        "feature_dim": prepared["x"].shape[1],
        "relation_names": prepared["relation_names"],
        "node_to_idx": prepared["node_to_idx"],
        "hidden_dim": 64,
        "latent_dim": 32,
        "trained_at": trained_at,
        "trigger": trigger,
        "final_loss": final_loss,
    }

    with tempfile.TemporaryDirectory() as temporary_dir:
        artifact_path = Path(temporary_dir) / "latest.pt"
        torch.save(artifact, artifact_path)
        artifact_sha256 = upload_model(settings, artifact_path)

    if runtime is not None:
        runtime.install(artifact, artifact_sha256=artifact_sha256)

    return {
        "status": "completed",
        "trained_at": trained_at,
        "node_count": len(graph["nodes"]),
        "edge_count": len(graph["edges"]),
        "final_loss": final_loss,
        "graph_sha256": digest,
        "artifact_sha256": artifact_sha256,
    }


def main() -> None:
    result = train_once(
        Settings.from_env(),
        trigger=os.getenv("TRAIN_TRIGGER", "railway_cron"),
    )
    print(result, flush=True)


if __name__ == "__main__":
    main()

