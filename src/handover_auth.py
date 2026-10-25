"""Verified Supabase Auth identity for LINK-ing handover APIs.

Only trusted Supabase app_metadata is used to authorize persons and team roles.
The common Railway HTTP Basic demo login is NOT person authentication.
"""
import json
import os
import urllib.error
import urllib.request
from fastapi import Header, HTTPException
from src.db import SupabaseStore

MARKETING = "marketing"
KNOWN_PERSONS = {"U0C20G9MRML", "U0C22C8M742", "U0C6WSR5275"}
MANAGER_ROLE = "manager"

def secure_handover_enabled():
    return os.getenv("HANDOVER_AUTH_MODE", "demo") == "verified"

def verified_actor(x_handover_access_token: str | None = Header(default=None)):
    """Validate each request using Supabase Auth, not an actor_id sent by browser."""
    if not secure_handover_enabled():
        return None
    if not x_handover_access_token:
        raise HTTPException(401, "User authentication required")
    token = x_handover_access_token
    if not token or len(token) > 8192:
        raise HTTPException(401, "Invalid access token")
    store = SupabaseStore()
    req = urllib.request.Request(
        store.url + "/auth/v1/user",
        headers={"apikey": store.key, "Authorization": "Bearer " + token},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            user = json.load(response)
    except urllib.error.HTTPError:
        raise HTTPException(401, "Invalid or expired session") from None
    except (urllib.error.URLError, ValueError):
        raise HTTPException(503, "Authentication service unavailable") from None

    metadata = user.get("app_metadata") or {}
    person_id = metadata.get("person_id")
    team = metadata.get("team")
    role = metadata.get("role")
    if not user.get("id") or team != MARKETING:
        raise HTTPException(403, "Marketing membership required")
    if role == MANAGER_ROLE:
        if not isinstance(person_id, str) or not person_id:
            raise HTTPException(403, "Manager person_id missing")
    elif person_id not in KNOWN_PERSONS:
        raise HTTPException(403, "Unrecognized employee identity")
    return {"person_id": person_id, "team": team, "role": role}

def can_approve(actor: dict, source_id: str) -> bool:
    return actor["role"] == MANAGER_ROLE or actor["person_id"] == source_id
