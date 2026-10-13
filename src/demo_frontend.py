"""Single-origin, password-protected Railway demo for the existing capstone backend.
Copy into src/demo_frontend.py in the slack branch; do not overwrite src/frontend_api.py.
"""
import os
import secrets
from pathlib import Path

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from src.db import SupabaseStore
from scripts.export_ml_rpc import fetch_graph
from src.frontend_api import app

ROOT = Path(__file__).resolve().parents[1]
SECURITY = HTTPBasic(auto_error=False)


def demo_auth(credentials: HTTPBasicCredentials | None = Depends(SECURITY)):
    """Browser HTTP Basic Auth for an isolated capstone demo, not YubiKey/SSO."""
    username = os.getenv('DEMO_USERNAME', '')
    password = os.getenv('DEMO_PASSWORD', '')
    if not username or not password:
        raise HTTPException(status_code=503, detail='Set DEMO_USERNAME and DEMO_PASSWORD')
    if credentials is None or not (
        secrets.compare_digest(credentials.username, username)
        and secrets.compare_digest(credentials.password, password)
    ):
        raise HTTPException(status_code=401, headers={'WWW-Authenticate': 'Basic realm="LINK-ing Demo"'}, detail='Authentication required')
    return True


@app.get('/', include_in_schema=False)
def demo_home(_=Depends(demo_auth)):
    return FileResponse(ROOT / 'frontend' / 'index.html', media_type='text/html', headers={'Cache-Control': 'no-store'})


@app.get('/demo_adapter.js', include_in_schema=False)
def demo_adapter(_=Depends(demo_auth)):
    return FileResponse(ROOT / 'frontend' / 'demo_adapter.js', media_type='application/javascript', headers={'Cache-Control': 'no-store'})


@app.get('/api/demo/data', include_in_schema=False)
def demo_data(_=Depends(demo_auth)):
    store = SupabaseStore()
    snapshot = store.snapshot()  # persons / events / tasks / works / edges
    messages = store.request('slack_messages', params={'select': '*', 'order': 'slack_ts.asc', 'limit': 200})
    graph = fetch_graph()  # existing graph-team Supabase RPC with tensor validation
    return {
        **snapshot,
        'slack_messages': messages,
        'graph': {'metadata': graph['metadata'], 'validation': graph['validation']},
        'source': 'Supabase (MCP/LLM-processed Slack demo)',
    }
