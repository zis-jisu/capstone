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

