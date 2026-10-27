"""Single-origin, password-protected Railway demo for the existing capstone backend.
Copy into src/demo_frontend.py in the slack branch; do not overwrite src/frontend_api.py.
"""
import os
import secrets
import logging
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from src.db import SupabaseStore, export_graph
from src.slack_login import actor as slack_actor, enabled as slack_login_enabled, begin as slack_begin, callback as slack_callback, logout as slack_logout
from src.frontend_api import app

ROOT = Path(__file__).resolve().parents[1]
SECURITY = HTTPBasic(auto_error=False)
FRONTEND_DB_SUFFIX = '_mock'
ORIGINAL_FRONTEND_WORK_ID = 'WORK-00020'


def _frontend_store():
    """Read the UI dataset from the isolated *_mock Supabase tables."""
    return SupabaseStore(table_suffix=FRONTEND_DB_SUFFIX)


def _all_messages(store):
    rows, offset = [], 0
    while True:
        batch = store.request('slack_messages', params={
            'select': '*', 'order': 'slack_ts.asc', 'limit': 500, 'offset': offset,
        })
        rows.extend(batch)
        if len(batch) < 500:
            return rows
        offset += len(batch)


def _without_work(snapshot, work_id):
    """Remove one Work subgraph while preserving unrelated mock Persons."""
    edges = snapshot['edges']
    task_ids = {edge['target_id'] for edge in edges
                if edge.get('source_type') == 'Work'
                and edge.get('source_id') == work_id
                and edge.get('target_type') == 'Task'
                and edge.get('relation') == 'HAS_TASK'}
    event_ids = {edge['target_id'] for edge in edges
                 if edge.get('source_type') == 'Task'
                 and edge.get('source_id') in task_ids
                 and edge.get('target_type') == 'Event'
                 and edge.get('relation') == 'HAS_EVENT'}
    node_ids = {work_id} | task_ids | event_ids
    return {
        'persons': list(snapshot['persons']),
        'works': [row for row in snapshot['works'] if row.get('work_id') != work_id],
        'tasks': [row for row in snapshot['tasks'] if row.get('task_id') not in task_ids],
        'events': [row for row in snapshot['events'] if row.get('event_id') not in event_ids],
        'edges': [edge for edge in edges
                  if edge.get('source_id') not in node_ids
                  and edge.get('target_id') not in node_ids],
    }, event_ids


def _merge_rows(base, overlay, key):
    merged = {row[key]: row for row in base}
    merged.update({row[key]: row for row in overlay})
    return list(merged.values())


def _overlay_original_work(mock_snapshot, original):
    mock, removed_event_ids = _without_work(mock_snapshot, ORIGINAL_FRONTEND_WORK_ID)
    scoped, _ = _filter_work_data(original, [], {ORIGINAL_FRONTEND_WORK_ID})
    mock['persons'] = _merge_rows(mock['persons'], scoped['persons'], 'person_id')
    mock['works'] = _merge_rows(mock['works'], scoped['works'], 'work_id')
    mock['tasks'] = _merge_rows(mock['tasks'], scoped['tasks'], 'task_id')
    mock['events'] = _merge_rows(mock['events'], scoped['events'], 'event_id')
    edge_key = lambda row: (row.get('source_id'), row.get('relation'), row.get('target_id'))
    edges = {edge_key(row): row for row in mock['edges']}
    edges.update({edge_key(row): row for row in scoped['edges']})
    mock['edges'] = list(edges.values())
    return mock, removed_event_ids, scoped


def _hybrid_frontend_snapshot():
    """Use *_mock by default, but source WORK-00020 from original tables."""
    snapshot, _, _ = _overlay_original_work(
        _frontend_store().snapshot(), SupabaseStore().snapshot())
    return snapshot


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



@app.get('/api/demo/my-works')
def demo_my_works(person_id: str = '', _=Depends(demo_auth), identity=Depends(slack_actor)):
    """Explicit on-demand Supabase read: participant (OWNER/REVIEWER/COLLABORATOR) -> Task -> Work.
    Demo person picker is not authenticated; verified Slack identity takes precedence.
    No mock Work is inserted when the DB has no corresponding edges.
    """
    members = {
        'U0C20G9MRML', 'U0C22C8M742', 'U0C6WSR5275', 'U0C38J2MUF4'
    }
    selected = identity['person_id'] if identity else person_id
    if selected not in members:
        raise HTTPException(422, 'Unknown demo team member')
    snapshot = _hybrid_frontend_snapshot()
    people = {p['person_id']:p.get('name') or p['person_id'] for p in snapshot['persons']}
    task_rows = {t['task_id']:t for t in snapshot['tasks']}
    event_rows = {e['event_id']:e for e in snapshot['events']}
    tasks_by_work = {}
    roles_by_task = {}
    events_by_task = {}
    my_tasks = set()
    accepted = {'OWNER','COLLABORATOR','REVIEWER','RELATED','ASSIGNEE'}
    for edge in snapshot['edges']:
        relation = str(edge.get('relation','')).upper()
        if edge.get('source_type') == 'Work' and edge.get('target_type') == 'Task' and relation == 'HAS_TASK':
            tasks_by_work.setdefault(edge['source_id'],[]).append(edge['target_id'])
        elif edge.get('source_type') == 'Person' and edge.get('target_type') == 'Task':
            role = relation if relation in accepted else str(edge.get('role') or '').upper()
            if role in accepted:
                roles_by_task.setdefault(edge['target_id'],[]).append({
                    'person_id':edge['source_id'], 'name':people.get(edge['source_id'],edge['source_id']),
                    'role':role
                })
                if edge['source_id'] == selected:
                    my_tasks.add(edge['target_id'])
        elif edge.get('source_type') == 'Task' and edge.get('target_type') == 'Event' and relation == 'HAS_EVENT':
            events_by_task.setdefault(edge['source_id'],[]).append(edge['target_id'])
    result=[]
    for work in snapshot['works']:
        ids=tasks_by_work.get(work['work_id'],[])
        if not my_tasks.intersection(ids):
            continue
        tasks=[]
        for tid in ids:
            t=task_rows.get(tid)
            if not t: continue
            roles=roles_by_task.get(tid,[])
            owners=[r['name'] for r in roles if r['role']=='OWNER']
            events=[event_rows[eid] for eid in events_by_task.get(tid,[]) if eid in event_rows]
            events.sort(key=lambda e:str(e.get('slack_ts') or ''))
            evidence=next((e.get('evidence') for e in events if e.get('evidence')),None)
            tasks.append({
                'task_id':tid, 'title':t.get('title') or t.get('subject') or tid,
                'status':t.get('status') or 'unknown',
                'deadline_text':t.get('deadline_text'),
                'deadline_at':t.get('deadline_at'),
                'next_action':t.get('next_action'),
                'owner':', '.join(owners) if owners else None,
                'participants':roles,
                'my_roles':[r['role'] for r in roles if r['person_id']==selected],
                'evidence':evidence,
                'evidence_event_id':events[0]['event_id'] if events else None
            })
        result.append({'work_id':work['work_id'],'title':work.get('title') or work['work_id'],
                       'tasks':tasks,'my_task_count':len(set(ids)&my_tasks)})
    return {'person_id':selected,'works':result,'count':len(result),'source':'supabase',
            'loaded_at':datetime.now(timezone.utc).isoformat(),
            'authenticated':bool(identity)}

@app.get('/api/demo/data', include_in_schema=False)
def demo_data(_=Depends(demo_auth), actor=Depends(slack_actor)):
    mock_store = _frontend_store()
    original_store = SupabaseStore()
    raw_mock = mock_store.snapshot()
    snapshot, removed_mock_event_ids, original_work = _overlay_original_work(
        raw_mock, original_store.snapshot())
    removed_mock_source_ids = {event.get('source_id') for event in raw_mock['events']
                               if event.get('event_id') in removed_mock_event_ids}
    original_source_ids = {event.get('source_id') for event in original_work['events']}
    mock_messages = [row for row in _all_messages(mock_store)
                     if row.get('message_id') not in removed_mock_source_ids]
    original_messages = [row for row in _all_messages(original_store)
                         if row.get('message_id') in original_source_ids]
    messages = _merge_rows(mock_messages, original_messages, 'message_id')
    graph = export_graph(snapshot)
    if actor:
        # In verified mode, an employee may only retrieve an approved Work.
        # Supervisors and the original handover source can review the source dataset.
        if actor['person_id'] != JISOO_ID:
            grants = _handover_db(params={
                'select': 'work_id',
                'requester_id': 'eq.' + actor['person_id'],
                'status': 'eq.approved',
            })
            allowed_work_ids = {g['work_id'] for g in grants}
            snapshot, messages = _filter_work_data(snapshot, messages, allowed_work_ids)
        # Graph ML metadata is summary only; no raw graph nodes are exposed here.
    return {
        **snapshot,
        'slack_messages': messages,
        'graph': {'metadata': graph['metadata']},
        'source': 'Supabase mock UI dataset + original WORK-00020',
        'data_sources': {
            'default': '*_mock',
            ORIGINAL_FRONTEND_WORK_ID: 'original',
        },
    }

def _filter_work_data(snapshot, messages, allowed_work_ids):
    """Keep only evidence attached to authorized Works, never all persons/events."""
    permitted_works = {w['work_id'] for w in snapshot['works']
                       if w['work_id'] in allowed_work_ids}
    edges = snapshot['edges']
    task_ids = {e['target_id'] for e in edges
                if e['source_type'] == 'Work' and e['source_id'] in permitted_works
                and e['relation'] == 'HAS_TASK'}
    event_ids = {e['target_id'] for e in edges
                 if e['source_type'] == 'Task' and e['source_id'] in task_ids
                 and e['relation'] == 'HAS_EVENT'}
    person_ids = {e['source_id'] for e in edges
                  if e['source_type'] == 'Person' and e['target_id'] in task_ids | event_ids}
    scoped_edges = [e for e in edges if (
        (e['source_type'] == 'Work' and e['source_id'] in permitted_works and e['target_id'] in task_ids)
        or (e['source_type'] == 'Task' and e['source_id'] in task_ids
            and ((e['target_type'] == 'Event' and e['target_id'] in event_ids)
                 or (e['target_type'] == 'Task' and e['target_id'] in task_ids)))
        or (e['source_type'] == 'Person' and e['source_id'] in person_ids
            and e['target_id'] in task_ids | event_ids))]
    selected_events = [e for e in snapshot['events'] if e['event_id'] in event_ids]
    source_ids = {e.get('source_id') for e in selected_events}
    result = {
        'works': [w for w in snapshot['works'] if w['work_id'] in permitted_works],
        'tasks': [t for t in snapshot['tasks'] if t['task_id'] in task_ids],
        'events': selected_events,
        'persons': [p for p in snapshot['persons'] if p['person_id'] in person_ids],
        'edges': scoped_edges,
    }
    return result, [m for m in messages if m.get('message_id') in source_ids]


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


def manager_auth(
    _=Depends(demo_auth), identity=Depends(slack_actor),
    x_demo_role: Annotated[str | None, Header()] = None,
):
    # The existing account picker is a Basic-auth-protected UI demonstration.
    # Never trust its role header when verified Slack login is enabled.
    if slack_login_enabled():
        allowed = {value.strip() for value in os.getenv('MANAGER_PERSON_IDS', '').split(',') if value.strip()}
        if not identity or identity['person_id'] not in allowed:
            raise HTTPException(403, 'Manager login required')
    elif x_demo_role != 'manager':
        raise HTTPException(403, 'Manager demo role required')
    return True


class AssignmentRequest(BaseModel):
    work_id: str | None = Field(default=None, min_length=1, max_length=90)
    task_id: str | None = Field(default=None, min_length=1, max_length=90)
    source_person_id: str | None = Field(default=None, min_length=1, max_length=50)
    assignee_id: str = Field(min_length=1, max_length=50)


class CollectRequest(BaseModel):
    person_id: str = Field(pattern=r'^U[A-Z0-9]+$', max_length=40)
    days: int = Field(default=90, ge=1, le=90)


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


from src import ml_bridge

class PriorityBody(BaseModel):
    person_id: str = Field(pattern=r'^U[A-Z0-9]+$', max_length=40)


@app.get('/api/ml/training')
def ml_training_status(_=Depends(demo_auth)):
    return ml_bridge.training_status()


@app.post('/api/admin/ml/training')
def ml_start_training(_=Depends(admin_auth)):
    return ml_bridge.stream_training()


@app.post('/api/ml/priorities')
def ml_priorities(body: PriorityBody, _=Depends(demo_auth)):
    return ml_bridge.priorities(body.person_id)


class WorkSyncRequest(BaseModel):
    work_id: str = Field(default='WORK-00020', pattern=r'^WORK-00020$')
    days: int = Field(default=90, ge=1, le=90)


_work_sync_task = None


@app.post('/api/demo/slack-link')
async def demo_slack_link(body: WorkSyncRequest = WorkSyncRequest(), _=Depends(admin_auth)):
    """Admin-only on-demand MCP collection -> extraction/save -> graph check -> ML."""
    global _work_sync_task
    from fastapi.responses import StreamingResponse
    from src.work_sync import work_scope, evidence_threads, apply_collection
    if not os.getenv('SLACK_TOKEN', '').strip():
        raise HTTPException(503, 'Railway linking-web에 SLACK_TOKEN을 설정하세요.')
    if _work_sync_task is not None and not _work_sync_task.done():
        raise HTTPException(409, 'WORK-00020 Slack 연동이 이미 진행 중입니다.')
    queue = asyncio.Queue()

    async def execute():
        from src.sync_errors import sync_error_detail, exception_leaves
        saved = None
        stage = 'database'
        try:
            store = SupabaseStore()
            before = await asyncio.to_thread(store.snapshot)
            scope = work_scope(before)
            threads = evidence_threads(scope)
            await queue.put({'status': 'running', 'stage': 'collect', 'progress_percent': 0,
                             'message': f'WORK-00020 · 최근 {body.days}일 · {len(threads)}개 근거 스레드 MCP 수집 중'})
            stage = 'collect'
            raw = await asyncio.wait_for(_call_slack_mcp('collect_slack_work_threads',
                {'work_id': body.work_id, 'threads': threads, 'days': body.days}), timeout=300)
            await queue.put({'status': 'running', 'stage': 'extract', 'progress_percent': 0,
                             'message': f"Slack {len(raw['records'])}건 수집 완료 · 변경 확인 및 Event/Task/Work 처리 중"})
            stage = 'extract'
            saved = await asyncio.to_thread(apply_collection, store, before, scope, raw, threads)
            await queue.put({'status': 'running', 'stage': 'saved', 'sync': saved,
                             'message': f"WORK-00020 동기화 확인 · 메시지 {saved['messages']}건 / 변경 {saved['changed_messages']}건 · 그래프 검증 중"})
            # Confirm the original-table RPC actually contains the synced Work before ML starts.
            stage = 'graph'
            from scripts.export_ml_rpc import fetch_graph
            graph = await asyncio.to_thread(fetch_graph)
            if not any(node.get('id') == body.work_id for node in graph['nodes']):
                raise ValueError('WORK-00020 is missing from the ML graph RPC')
            stage = 'training'
            training = await asyncio.to_thread(ml_bridge.stream_training)
            buffer, completed = '', False
            async for chunk in training.body_iterator:
                buffer += chunk.decode() if isinstance(chunk, bytes) else chunk
                lines = buffer.split('\n'); buffer = lines.pop()
                for line in lines:
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if event.get('status') == 'failed':
                        raise RuntimeError('ML training failed')
                    completed = completed or event.get('status') == 'completed'
                    if event.get('status') != 'completed':
                        await queue.put({**event, 'stage': 'training', 'sync': saved})
            if buffer.strip():
                final = json.loads(buffer)
                if final.get('status') == 'failed':
                    raise RuntimeError('ML training failed')
                completed = completed or final.get('status') == 'completed'
            if not completed:
                raise RuntimeError('ML training did not confirm completion')
            await queue.put({'status': 'completed', 'stage': 'completed', 'sync': saved,
                             'message': 'WORK-00020 Slack 동기화 및 ML 학습 완료'})
        except Exception as exc:
            detail = sync_error_detail(exc, stage)
            kinds = ','.join(sorted({type(e).__name__ for e in exception_leaves(exc)}))
            import traceback
            frames = ';'.join(Path(frame.filename).name + ':' + str(frame.lineno) + ':' + frame.name
                              for leaf in exception_leaves(exc) for frame in traceback.extract_tb(leaf.__traceback__))
            logging.getLogger(__name__).error('WORK20_SYNC stage=%s exceptions=%s detail=%s frames=%s', stage, kinds, detail, frames)
            await queue.put({'status': 'failed', 'stage': stage, 'error': detail, 'sync': saved})
        finally:
            await queue.put(None)

    # Task survives a browser disconnect, preventing duplicate extraction and writes.
    _work_sync_task = asyncio.create_task(execute())

    async def events():
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield json.dumps({'status': 'running', 'stage': 'heartbeat', 'message': 'WORK-00020 처리 중'}) + '\n'
                continue
            if event is None:
                break
            yield json.dumps(event, ensure_ascii=False) + '\n'
    return StreamingResponse(events(), media_type='application/x-ndjson',
                             headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})


@app.get('/api/demo/meta')
def demo_meta(_=Depends(demo_auth)):
    try:
        ml_status = ml_bridge.training_status()
        trained_at = ml_bridge.trained_at(ml_status)
    except HTTPException:
        trained_at = None
    snapshot = _frontend_store().snapshot()
    event_updates = [e.get('updated_at') for e in snapshot['events'] if e.get('updated_at')]
    return {'model_trained_at': trained_at, 'last_analyzed_at': max(event_updates, default=None),
            'model_training_source': 'ml_api' if trained_at else 'not_connected'}


@app.get('/api/admin/validate')
def validate_admin(_=Depends(admin_auth)):
    return {'ok':True}


@app.get('/api/admin/assignments')
def list_assignments(_=Depends(admin_auth)):
    return {'assignments':_db_assignments(params={'select':'*','order':'assigned_at.desc','limit':'100'})}


@app.post('/api/admin/assignments',status_code=201)
def create_assignment(body:AssignmentRequest, _=Depends(admin_auth)):
    # A handover recipient must not be silently promoted to the original OWNER edge.
    snap=_hybrid_frontend_snapshot()
    tasks = {t['task_id']:t for t in snap['tasks']}
    works = {w['work_id']:w for w in snap['works']}
    if not body.work_id and not body.task_id:
        raise HTTPException(422,'work_id is required')
    if body.assignee_id not in {p['person_id'] for p in snap['persons']}:
        raise HTTPException(404,'Unknown person')
    if body.source_person_id and body.source_person_id not in {p['person_id'] for p in snap['persons']}:
        raise HTTPException(404,'Unknown source person')
    if body.source_person_id == body.assignee_id:
        raise HTTPException(422,'Source person and recipient must be different')
    if body.work_id:
        if body.work_id not in works:
            raise HTTPException(404,'Unknown Work')
        work_task_ids = {e['target_id'] for e in snap['edges']
                         if e.get('source_type') == 'Work'
                         and e.get('source_id') == body.work_id
                         and e.get('target_type') == 'Task'
                         and e.get('relation') == 'HAS_TASK'}
        task_ids = [task_id for task_id in work_task_ids
                    if task_id in tasks
                    and str(tasks[task_id].get('status','')).lower() != 'completed']
        if body.source_person_id:
            owned = {e['target_id'] for e in snap['edges']
                     if e.get('source_type') == 'Person'
                     and e.get('source_id') == body.source_person_id
                     and e.get('target_type') == 'Task'
                     and e.get('relation') == 'OWNER'}
            if not owned.intersection(work_task_ids):
                raise HTTPException(422,'Selected person is not an owner of this Work')
    else:
        if body.task_id not in tasks:
            raise HTTPException(404,'Unknown Task')
        task_ids = [body.task_id]
    if not task_ids:
        raise HTTPException(409,'This Work has no unfinished Tasks')
    actor=os.getenv('ADMIN_ACTOR_ID','')
    if actor not in {p['person_id'] for p in snap['persons']}:
        raise HTTPException(503,'Configure ADMIN_ACTOR_ID as a valid person ID')
    rows=_db_assignments(method='POST',rows=[
        {'task_id':task_id,'assignee_id':body.assignee_id,'assigned_by':actor}
        for task_id in sorted(task_ids)
    ])
    priority_result = None
    priority_error = None
    try:
        # Manager assignment calculates priorities for the selected recipient,
        # never for a fixed demo person.
        priority_result = ml_bridge.priorities(body.assignee_id)
    except HTTPException as exc:
        priority_error = str(exc.detail)
    except Exception:
        priority_error = 'ML priority response could not be processed'
    return {'assignment':rows[0], 'assignments':rows, 'work_id':body.work_id,
            'task_ids':sorted(task_ids), 'priorities':priority_result,
            'priority_error':priority_error}


async def _call_slack_mcp(tool_name, arguments):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    if not os.getenv('SLACK_TOKEN'):
        raise HTTPException(503,'SLACK_TOKEN is not configured on Railway')
    params=StdioServerParameters(command=sys.executable,args=['-m','src.slack.mcp_server'],cwd=str(ROOT),env=dict(os.environ))
    async with stdio_client(params) as (reader,writer):
        async with ClientSession(reader,writer) as session:
            await session.initialize()
            result=await session.call_tool(tool_name,arguments)
    # Parse after the AnyIO task-group contexts have closed: raising inside them
    # can wrap a useful HTTPException in ExceptionGroup and obscure its cause.
    if result.isError:
        from src.sync_errors import sync_error_detail
        detail = ' '.join(block.text for block in result.content if getattr(block, 'type', None) == 'text')
        safe = sync_error_detail(RuntimeError(detail), 'collect')
        if '서버의 WORK20_SYNC' in safe:
            safe = 'MCP collection failed'
        raise HTTPException(502, safe)
    content = result.structuredContent
    if content is None:
        content=json.loads(result.content[0].text)
    if isinstance(content,dict) and 'result' in content and isinstance(content['result'],dict):
        content=content['result']
    if not isinstance(content,dict) or not isinstance(content.get('records'),list):
        raise HTTPException(502,'Unexpected MCP response')
    return content


async def _collect_via_mcp(person_id, days=90):
    return await _call_slack_mcp('collect_slack_person_work', {'person_id': person_id, 'days': days})


@app.get('/api/manager/assignments')
def manager_assignments(_=Depends(manager_auth)):
    return list_assignments()


@app.post('/api/manager/assignments', status_code=201)
def manager_create_assignment(body: AssignmentRequest, _=Depends(manager_auth)):
    return create_assignment(body)


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

@app.get('/api/demo/auth/config')
def demo_auth_config(_=Depends(demo_auth)):
    return {'verified_mode': slack_login_enabled(), 'provider': 'slack'}

@app.get('/api/demo/auth/slack/start')
def slack_signin(_=Depends(demo_auth)):
    return slack_begin()

@app.get('/api/demo/auth/slack/callback')
def slack_signin_callback(code: str, state: str, request: Request):
    return slack_callback(code, state, request)

@app.get('/api/demo/auth/me')
def slack_me(_=Depends(demo_auth), identity=Depends(slack_actor)):
    if not identity:
        return {'authenticated': False, 'mode': 'demo'}
    return {'authenticated': True, 'person_id': identity['person_id']}

@app.get('/api/demo/auth/logout')
def slack_signout(_=Depends(demo_auth)):
    return slack_logout()

@app.get('/api/demo/handover-catalog')
def demo_handover_catalog(source_person_id: str, _=Depends(demo_auth), actor=Depends(slack_actor)):
    # Request selection needs Work/Task titles before approval, never Event text or raw Slack.
    from src.handover_catalog import handover_catalog
    snapshot = _hybrid_frontend_snapshot()
    if source_person_id not in {p['person_id'] for p in snapshot['persons']}:
        raise HTTPException(404, 'Unknown handover source person')
    return {'source_person_id': source_person_id, 'works': handover_catalog(snapshot, source_person_id)}


@app.get('/api/demo/handover-requests')
def demo_handover_list(_=Depends(demo_auth), actor=Depends(slack_actor)):
    rows = _handover_db(params={'select': '*', 'order': 'created_at.desc', 'limit': '100'})
    if actor:
        rows = [r for r in rows if actor['person_id'] in (r['requester_id'], r['source_person_id'])]
    return {'requests': rows}

@app.post('/api/demo/handover-requests', status_code=201)
def demo_handover_create(body: DemoHandoverRequest, _=Depends(demo_auth), actor=Depends(slack_actor)):
    if actor and actor['person_id'] != body.requester_id:
        raise HTTPException(403, 'Cannot request on behalf of another person')
    snapshot = _hybrid_frontend_snapshot()
    person_ids = {person['person_id'] for person in snapshot['persons']}
    work_ids = {work['work_id'] for work in snapshot['works']}
    if body.requester_id not in person_ids or body.source_person_id not in person_ids:
        raise HTTPException(404, 'Unknown handover person')
    if body.work_id not in work_ids:
        raise HTTPException(404, 'Unknown Work')
    if body.requester_id == body.source_person_id:
        raise HTTPException(422, 'Requester and source person must differ')
    rows = _handover_db('POST', payload={
        'requester_id': body.requester_id,
        'source_person_id': body.source_person_id,
        'work_id': body.work_id,
        'status': 'pending',
    })
    return {'request': rows[0]}

@app.post('/api/demo/handover-requests/{request_id}/decision')
def demo_handover_decide(request_id: str, body: DemoHandoverDecision, _=Depends(demo_auth), actor=Depends(slack_actor)):
    from uuid import UUID
    try:
        UUID(request_id)
    except ValueError:
        raise HTTPException(422, 'Invalid request ID') from None
    if actor and actor['person_id'] != body.actor_id:
        raise HTTPException(403, 'Actor mismatch')
    rows = _handover_db(params={
        'select': '*', 'request_id': 'eq.' + request_id, 'status': 'eq.pending',
    })
    if not rows:
        raise HTTPException(409, 'Request is not pending')
    if body.actor_id != rows[0]['source_person_id']:
        raise HTTPException(403, 'Approval permission denied')
    patch = {'status': body.status, 'approved_by': body.actor_id,
             'verification_method': 'demo_yubikey' if body.status == 'approved' else None,
             'approved_at': datetime.now(timezone.utc).isoformat() if body.status == 'approved' else None}
    updated = _handover_db('PATCH', params={
        'request_id': 'eq.' + request_id, 'status': 'eq.pending',
    }, payload=patch)
    if not updated:
        raise HTTPException(409, 'Request was already processed')
    priority_result = None
    priority_error = None
    if body.status == 'approved':
        try:
            # Approval is already committed. Calculate for the actual approver
            # (the source person whose Tasks are being handed over) and return
            # the result in the same response for frontend storage.
            priority_result = ml_bridge.priorities(updated[0]['approved_by'])
        except HTTPException as exc:
            priority_error = str(exc.detail)
        except Exception:
            priority_error = 'ML priority response could not be processed'
    return {'request': updated[0], 'priorities': priority_result,
            'priority_error': priority_error}
