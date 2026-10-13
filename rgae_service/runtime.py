from __future__ import annotations

import threading
import time
from typing import Any

import torch

from .config import Settings
from .graph import graph_digest, normalize_graph
from .model import RelationalGraphAutoencoder, prepare_graph, resolve_device
from .repository import download_model


class ModelRuntime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.device = resolve_device(settings.device)
        self.lock = threading.RLock()
        self.refresh_lock = threading.Lock()
        self.graph: dict[str, Any] | None = None
        self.prepared: dict[str, Any] | None = None
        self.model: RelationalGraphAutoencoder | None = None
        self.seed: int | None = None
        self.record: dict[str, Any] | None = None
        self.artifact_sha256: str | None = None
        self.last_refresh_check = 0.0

    def load_latest(self) -> bool:
        destination = self.settings.model_cache_dir / "latest.pt"
        digest = download_model(self.settings, destination)
        if digest is None:
            return False
        with self.lock:
            if digest == self.artifact_sha256:
                return False
        checkpoint = torch.load(destination, map_location="cpu", weights_only=False)
        self.install(checkpoint, artifact_sha256=digest)
        return True

    def refresh_if_due(self, force: bool = False) -> bool:
        """Reload a model written by the separate Railway Cron service."""
        now = time.monotonic()
        with self.refresh_lock:
            if (
                not force
                and now - self.last_refresh_check
                < self.settings.model_refresh_seconds
            ):
                return False
            self.last_refresh_check = now
            return self.load_latest()

    def install(
        self,
        checkpoint: dict[str, Any],
        artifact_sha256: str | None = None,
    ) -> None:
        graph = normalize_graph(checkpoint["graph"])
        if graph_digest(graph) != checkpoint["graph_sha256"]:
            raise RuntimeError("model artifact and graph checksum do not match")
        prepared = prepare_graph(graph, int(checkpoint["seed"]))
        if prepared["node_to_idx"] != checkpoint["node_to_idx"]:
            raise RuntimeError("model node index does not match its graph")
        model = RelationalGraphAutoencoder(
            checkpoint["feature_dim"],
            checkpoint["hidden_dim"],
            checkpoint["latent_dim"],
            len(checkpoint["relation_names"]),
        ).to(self.device)
        model.load_state_dict(checkpoint["model_state_dict"])
        model.eval()
        with self.lock:
            self.graph = graph
            self.prepared = prepared
            self.model = model
            self.seed = int(checkpoint["seed"])
            self.artifact_sha256 = artifact_sha256
            self.record = {
                "trained_at": checkpoint["trained_at"],
                "node_count": len(graph["nodes"]),
                "edge_count": len(graph["edges"]),
                "final_loss": checkpoint.get("final_loss"),
                "graph_sha256": checkpoint["graph_sha256"],
                "artifact_sha256": artifact_sha256,
            }

    def snapshot(self):
        with self.lock:
            if self.model is None:
                raise RuntimeError("no completed model is available yet")
            return (
                self.graph,
                self.prepared,
                self.model,
                self.seed,
                dict(self.record or {}),
            )

    def metadata(self) -> dict[str, Any]:
        with self.lock:
            return {
                "model_loaded": self.model is not None,
                "latest_model": dict(self.record) if self.record else None,
            }

