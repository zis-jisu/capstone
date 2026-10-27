"""Server-side bridge to the ML Railway API. API credentials never reach the browser."""
import json
import os
import urllib.error
import urllib.request

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

BASE = "https://capstone-production-0d32.up.railway.app"


def trained_at(status):
    """Return the latest model timestamp across current and legacy API shapes."""
    last_result = status.get("last_result") or {}
    latest_model = status.get("latest_model") or {}
    return (
        status.get("model_trained_at")
        or last_result.get("model_trained_at")
        or last_result.get("trained_at")
        or latest_model.get("trained_at")
    )

def _base_url():
    base = os.getenv("MODEL_API_URL", BASE).strip().strip("<>").rstrip("/")
    if base and "://" not in base and base.endswith(".railway.app"):
        base = "https://" + base
    for suffix in ("/v1/training", "/v1/priorities", "/v1"):
        if base.endswith(suffix):
            base = base[:-len(suffix)]
            break
    return base


def configuration_status():
    return {
        "configured": bool(os.getenv("MODEL_API_KEY", "").strip()) and _base_url().startswith("https://"),
        "base_url": _base_url(),
    }


def _settings():
    key = os.getenv("MODEL_API_KEY", "").strip()
    if not key:
        raise HTTPException(503, "MODEL_API_KEY is not configured on LINK-ing Railway")
    base = _base_url()
    if not base.startswith("https://"):
        raise HTTPException(503, "MODEL_API_URL must use HTTPS")
    return base, key

def _open(path, method="GET", payload=None, timeout=30):
    base, key = _settings()
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(base + path, method=method, data=data, headers={
        "X-API-Key": key, "Content-Type": "application/json", "Accept": "application/json",
    })
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise HTTPException(502, f"ML API returned HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError):
        raise HTTPException(502, "ML API is unavailable") from None

def training_status():
    with _open("/v1/training") as response:
        return json.load(response)

def priorities(person_id):
    if not person_id:
        raise HTTPException(422, "person_id is required")
    with _open("/v1/priorities", method="POST", payload={"person_id": person_id}, timeout=90) as response:
        return json.load(response)

def stream_training():
    # Keep upstream connection open until its final NDJSON completed/failed event.
    upstream = _open("/v1/training", method="POST", payload={"trigger": "manual"}, timeout=240)
    def events():
        try:
            for line in upstream:
                if line.strip():
                    yield line
        except Exception:
            yield b'{"status":"failed","error":"Training connection interrupted"}\n'
        finally:
            upstream.close()
    return StreamingResponse(events(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
