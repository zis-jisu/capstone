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

# Admin functions are an isolated demo adapter; the existing pipeline remains unchanged.
import asyncio
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Annotated
from fastapi import Header
from pydantic import BaseModel, Field


def admin_auth(
    _=Depends(demo_auth),
    x_admin_token: Annotated[str | None, Header()] = None,
):
    expected = os.getenv('ADMIN_PASSWORD', '')
    if not expected:
        raise HTTPException(503, 'ADMIN_PASSWORD not configured')
    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(403, 'Admin authentication required')
    return True


class AssignmentRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=90)
    assignee_id: str = Field(min_length=1, max_length=50)


class CollectRequest(BaseModel):
    person_id: str = Field(pattern=r'^U[A-Z0-9]+$', max_length=40)
    days: int = Field(default=14, ge=1, le=90)


def _db_assignments(method='GET', params=None, rows=None):
    # Backend-only Supabase REST. Never send service credentials to the browser.
    store = SupabaseStore()
    uri = store.url + '/rest/v1/handover_assignments'
    if params:
        uri += '?' + urllib.parse.urlencode(params)
    data = None if rows is None else json.dumps(rows, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(uri, data=data, method=method, headers={
        'apikey':store.key, 'Authorization':'Bearer '+store.key,
        'Content-Type':'application/json', 'Prefer':'return=representation',
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            b=resp.read()
            return json.loads(b) if b else []
    except urllib.error.HTTPError:
        raise HTTPException(502, 'Failed to access assignment storage') from None


@app.get('/api/demo/meta')
def demo_meta(_=Depends(demo_auth)):
    # Training timestamps must be supplied by the real model training pipeline.
    trained_at = os.getenv('MODEL_TRAINED_AT') or None
    snapshot = SupabaseStore().snapshot()
    event_updates = [e.get('updated_at') for e in snapshot['events'] if e.get('updated_at')]
    return {'model_trained_at':trained_at, 'last_analyzed_at':max(event_updates,default=None),
            'model_training_source':'MODEL_TRAINED_AT' if trained_at else 'not_connected'}


@app.get('/api/admin/validate')
def validate_admin(_=Depends(admin_auth)):
    return {'ok':True}


@app.get('/api/admin/assignments')
def list_assignments(_=Depends(admin_auth)):
    return {'assignments':_db_assignments(params={'select':'*','order':'assigned_at.desc','limit':'100'})}


@app.post('/api/admin/assignments',status_code=201)
def create_assignment(body:AssignmentRequest, _=Depends(admin_auth)):
    # A handover recipient must not be silently promoted to the original OWNER edge.
    snap=SupabaseStore().snapshot()
    if body.task_id not in {t['task_id'] for t in snap['tasks']}:
        raise HTTPException(404,'Unknown Task')
    if body.assignee_id not in {p['person_id'] for p in snap['persons']}:
        raise HTTPException(404,'Unknown person')
    actor=os.getenv('ADMIN_ACTOR_ID','')
    if actor not in {p['person_id'] for p in snap['persons']}:
        raise HTTPException(503,'Configure ADMIN_ACTOR_ID as a valid person ID')
    rows=_db_assignments(method='POST',rows=[{'task_id':body.task_id,'assignee_id':body.assignee_id,'assigned_by':actor}])
    return {'assignment':rows[0]}


async def _collect_via_mcp(person_id, days):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    if not os.getenv('SLACK_TOKEN'):
        raise HTTPException(503,'SLACK_TOKEN is not configured on Railway')
    params=StdioServerParameters(command=sys.executable,args=['-m','src.slack.mcp_server'],cwd=str(ROOT),env=dict(os.environ))
    async with stdio_client(params) as (reader,writer):
        async with ClientSession(reader,writer) as session:
            await session.initialize()
            result=await session.call_tool('collect_slack_person_work',{'person_id':person_id,'days':days})
            if result.isError:
                raise HTTPException(502,'MCP collection failed')
            content=result.structuredContent
            if content is None:
                content=json.loads(result.content[0].text)
            if isinstance(content,dict) and 'result' in content and isinstance(content['result'],dict):
                content=content['result']
            if not isinstance(content,dict) or not isinstance(content.get('records'),list):
                raise HTTPException(502,'Unexpected MCP response')
            return content


@app.post('/api/admin/slack-collect')
async def admin_collect(body:CollectRequest, _=Depends(admin_auth)):
    # Collection preview ONLY: no LLM calls, no Supabase writes, no raw texts sent to UI.
    try:
        raw=await _collect_via_mcp(body.person_id,body.days)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502,'Slack MCP collection unavailable') from None
    return {'messages':len(raw['records']),'people':len(raw.get('people',[])),
            'channels':raw.get('metadata',{}).get('matched_channels',[]),
            'warnings':len(raw.get('metadata',{}).get('warnings',[])),
            'saved':False,'llm_executed':False}


@app.get('/admin_adapter.js',include_in_schema=False)
def admin_adapter_js(_=Depends(demo_auth)):
    return FileResponse(ROOT/'frontend'/'admin_adapter.js',media_type='application/javascript',headers={'Cache-Control':'no-store'})


@app.get('/logo.png', include_in_schema=False)
def demo_logo():
    logo = ROOT / 'frontend' / 'logo.png'
    if not logo.is_file():
        raise HTTPException(404, 'Logo asset not uploaded yet')
    return FileResponse(logo, media_type='image/png')


# Marketing handover approval DEMO API.
# HTTP Basic protects the site but does NOT establish person identity.
# The actor passed here is untrusted and is accepted for the demonstration only.
# Replace with a verified login/session and server-side team role checks before production.
JISOO_ID = 'U0C22C8M742'
WON_ID = 'U0C20G9MRML'
MARKETING_MANAGER_DEMO_ID = 'DEMO-MARKETING-MANAGER'
WORK_DEMO_ID = 'WORK-00020'

class DemoHandoverRequest(BaseModel):
    requester_id: str = Field(min_length=1, max_length=40)
    source_person_id: str = Field(min_length=1, max_length=40)
    work_id: str = Field(min_length=1, max_length=80)

class DemoHandoverDecision(BaseModel):
    actor_id: str = Field(min_length=1, max_length=40)
    status: str = Field(pattern='^(approved|rejected)$')

def _handover_db(method='GET', params=None, payload=None):
    store = SupabaseStore()
    url = store.url + '/rest/v1/handover_requests'
    if params:
        url += '?' + urllib.parse.urlencode(params)
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        'apikey': store.key, 'Authorization': 'Bearer ' + store.key,
        'Content-Type': 'application/json', 'Prefer': 'return=representation',
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read() or b'[]')
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            raise HTTPException(409, 'Already pending') from None
        raise HTTPException(502, 'Handover storage error') from None
    except urllib.error.URLError:
        raise HTTPException(502, 'Handover database unreachable') from None

@app.get('/api/demo/handover-requests')
def demo_handover_list(_=Depends(demo_auth)):
    return {'requests': _handover_db(params={'select': '*', 'order': 'created_at.desc', 'limit': '100'})}

@app.post('/api/demo/handover-requests', status_code=201)
def demo_handover_create(body: DemoHandoverRequest, _=Depends(demo_auth)):
    # Explicit one-scenario scope for the UI prototype.
    if (body.requester_id, body.source_person_id, body.work_id) != (WON_ID, JISOO_ID, WORK_DEMO_ID):
        raise HTTPException(422, 'Unsupported demo handover')
    rows = _handover_db('POST', payload={
        'requester_id': body.requester_id,
        'source_person_id': body.source_person_id,
        'work_id': body.work_id,
        'status': 'pending',
    })
    return {'request': rows[0]}

@app.post('/api/demo/handover-requests/{request_id}/decision')
def demo_handover_decide(request_id: str, body: DemoHandoverDecision, _=Depends(demo_auth)):
    from uuid import UUID
    try:
        UUID(request_id)
    except ValueError:
        raise HTTPException(422, 'Invalid request ID') from None
    if body.actor_id not in (JISOO_ID, MARKETING_MANAGER_DEMO_ID):
        raise HTTPException(403, 'Demo actor cannot approve')
    rows = _handover_db(params={
        'select': '*', 'request_id': 'eq.' + request_id, 'status': 'eq.pending',
    })
    if not rows:
        raise HTTPException(409, 'Request is not pending')
    if rows[0]['source_person_id'] != JISOO_ID:
        raise HTTPException(403, 'Outside of demo team')
    patch = {'status': body.status, 'approved_by': body.actor_id,
             'verification_method': 'demo_yubikey' if body.status == 'approved' else None,
             'approved_at': datetime.now(timezone.utc).isoformat() if body.status == 'approved' else None}
    updated = _handover_db('PATCH', params={
        'request_id': 'eq.' + request_id, 'status': 'eq.pending',
    }, payload=patch)
    if not updated:
        raise HTTPException(409, 'Request was already processed')
    return {'request': updated[0]}
