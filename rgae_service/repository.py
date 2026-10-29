from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from .config import Settings


def _headers(settings: Settings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.supabase_secret_key}",
        "apikey": settings.supabase_secret_key,
    }


def fetch_graph(settings: Settings) -> dict[str, Any]:
    response = httpx.post(
        f"{settings.supabase_url}/rest/v1/rpc/{quote(settings.graph_rpc, safe='')}",
        headers={**_headers(settings), "Content-Type": "application/json"},
        json={},
        timeout=120,
    )
    response.raise_for_status()
    graph = response.json()
    if not isinstance(graph, dict):
        raise RuntimeError("graph RPC did not return a JSON object")
    validation = graph.get("validation_summary") or {}
    if validation and validation.get("is_valid") is False:
        raise RuntimeError(f"graph validation failed: {validation}")
    return graph


def fetch_training_snapshot(
    settings: Settings, snapshot_key: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load one immutable training graph stored as JSONB in Supabase."""
    key = (snapshot_key or settings.training_snapshot_key).strip()
    if not key:
        raise ValueError("training snapshot key is required")
    response = httpx.get(
        f"{settings.supabase_url}/rest/v1/{quote(settings.training_snapshot_table, safe='')}",
        headers=_headers(settings),
        params={
            "select": "snapshot_key,snapshot_at,source_file,graph_json",
            "snapshot_key": f"eq.{key}",
            "limit": "1",
        },
        timeout=120,
    )
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"training graph snapshot does not exist: {key}")
    row = rows[0]
    graph = row.get("graph_json")
    if not isinstance(graph, dict):
        raise RuntimeError(f"training graph snapshot is not a JSON object: {key}")
    metadata = {
        "snapshot_key": row.get("snapshot_key") or key,
        "snapshot_at": row.get("snapshot_at"),
        "source_file": row.get("source_file"),
    }
    return graph, metadata


def upload_model(settings: Settings, local_path: Path) -> str:
    content = local_path.read_bytes()
    url = (
        f"{settings.supabase_url}/storage/v1/object/"
        f"{quote(settings.storage_bucket, safe='')}/"
        f"{quote(settings.model_object_path, safe='/')}"
    )
    response = httpx.put(
        url,
        headers={
            **_headers(settings),
            "x-upsert": "true",
            "Content-Type": "application/octet-stream",
        },
        content=content,
        timeout=180,
    )
    response.raise_for_status()
    return hashlib.sha256(content).hexdigest()


def download_model(settings: Settings, destination: Path) -> str | None:
    url = (
        f"{settings.supabase_url}/storage/v1/object/"
        f"{quote(settings.storage_bucket, safe='')}/"
        f"{quote(settings.model_object_path, safe='/')}"
    )
    response = httpx.get(url, headers=_headers(settings), timeout=180)
    # Supabase Storage can return HTTP 400 with an embedded 404/not_found
    # payload when an object has not been created yet. That is the normal
    # state before the first successful training, not an API failure.
    response_text = response.text.lower()
    if response.status_code == 404 or (
        response.status_code == 400
        and (
            "object not found" in response_text
            or '"statuscode":"404"' in response_text.replace(" ", "")
            or '"error":"not_found"' in response_text.replace(" ", "")
        )
    ):
        return None
    response.raise_for_status()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    return hashlib.sha256(response.content).hexdigest()

