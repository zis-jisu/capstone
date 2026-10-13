from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


def _required(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    raise RuntimeError(f"missing required environment variable: {' or '.join(names)}")


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_secret_key: str
    graph_rpc: str
    storage_bucket: str
    model_object_path: str
    model_cache_dir: Path
    model_refresh_seconds: int
    epochs: int
    seed: int
    device: str
    api_key: str
    allowed_origins: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        origins = tuple(
            item.strip()
            for item in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
            if item.strip()
        )
        return cls(
            supabase_url=_required("SUPABASE_URL").rstrip("/"),
            supabase_secret_key=_required(
                "SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY"
            ),
            graph_rpc=os.getenv("GRAPH_RPC", "get_graph_snapshot"),
            storage_bucket=os.getenv("MODEL_BUCKET", "rgae-models"),
            model_object_path=os.getenv("MODEL_OBJECT_PATH", "models/latest.pt"),
            model_cache_dir=Path(
                os.getenv(
                    "MODEL_CACHE_DIR",
                    str(Path(tempfile.gettempdir()) / "rgae-models"),
                )
            ),
            model_refresh_seconds=max(
                0, int(os.getenv("MODEL_REFRESH_SECONDS", "60"))
            ),
            epochs=int(os.getenv("RGAE_EPOCHS", "100")),
            seed=int(os.getenv("RGAE_SEED", "42")),
            device=os.getenv("RGAE_DEVICE", "cpu"),
            api_key=os.getenv("MODEL_API_KEY", ""),
            allowed_origins=origins,
        )

