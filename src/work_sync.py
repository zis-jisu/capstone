"""Bounded WORK-00020 sync; no discovery or writes to other Work graphs."""
import json
import os
import re
from pathlib import Path
from src.pipeline import normalize_messages, run_pipeline
from src.db import to_db, TABLE_KEYS
from scripts.sync_slack import digest, identity_conflicts

WORK_ID = 'WORK-00020'


def work_scope(snapshot):
    works = [w for w in snapshot['works'] if w['work_id'] == WORK_ID]
    if len(works) != 1:
        raise ValueError('WORK-00020 must already exist in the original tables')
    task_ids = {e['target_id'] for e in snapshot['edges']
                if e['source_id'] == WORK_ID and e['relation'] == 'HAS_TASK'
                and e['source_type'] == 'Work' and e['target_type'] == 'Task'}
    if not task_ids:
        raise ValueError('WORK-00020 has no linked Tasks')
    if any(e['relation'] == 'HAS_TASK' and e['target_id'] in task_ids
           and e['source_type'] == 'Work' and e['source_id'] != WORK_ID for e in snapshot['edges']):
        raise ValueError('A Task is shared with another Work; reconcile its scope first')
    event_ids = {e['target_id'] for e in snapshot['edges']
                 if e['source_id'] in task_ids and e['relation'] == 'HAS_EVENT'
                 and e['source_type'] == 'Task' and e['target_type'] == 'Event'}
    if any(e['relation'] == 'HAS_EVENT' and e['target_id'] in event_ids
           and e['source_type'] == 'Task' and e['source_id'] not in task_ids for e in snapshot['edges']):
        raise ValueError('An Event is shared with another Work; reconcile its scope first')
    node_ids = {WORK_ID} | task_ids | event_ids
    edges = [e for e in snapshot['edges']
             if e['target_id'] in node_ids and (e['source_id'] in node_ids or e['source_type'] == 'Person')]
    person_ids = {e['source_id'] for e in edges if e['source_type'] == 'Person'}
    return {'works': works, 'tasks': [t for t in snapshot['tasks'] if t['task_id'] in task_ids],
            'events': [e for e in snapshot['events'] if e['event_id'] in event_ids],
            'persons': [p for p in snapshot['persons'] if p['person_id'] in person_ids], 'edges': edges}


def evidence_threads(scope):
    roots = set()
    for event in scope['events']:
        source = event.get('source_id', '')
        channel, sep, ts = source.partition(':')
        channel = event.get('conversation_id') or channel
        ts = event.get('parent_ts') or ts
        if not sep or not re.fullmatch(r'[CDG][A-Z0-9]+', channel) or not re.fullmatch(r'[0-9]+\.[0-9]+', ts):
            raise ValueError('WORK-00020 evidence is missing a real Slack channel/thread')
        roots.add((channel, ts))
    if not roots:
        raise ValueError('WORK-00020 has no Slack evidence threads')
    return [{'channel_id': channel, 'thread_ts': ts} for channel, ts in sorted(roots)]


def prior_messages(store, threads):
    rows = {}
    # Only inspect the explicitly scoped threads. Include their parent messages too.
    for thread in threads:
        channel, root = thread['channel_id'], thread['thread_ts']
        offset = 0
        while True:
            page = store.request('slack_messages', params={
                'select': '*', 'conversation_id': 'eq.' + channel,
                'or': f'(parent_ts.eq.{root},message_id.eq.{channel}:{root})',
                'order': 'message_id.asc', 'limit': 500, 'offset': offset})
            rows.update({row['message_id']: row for row in page})
            if len(page) < 500:
                break
            offset += len(page)
    return rows


def apply_collection(store, before, scope, raw, threads, *, run=run_pipeline, plan_dir=None):
    folder = Path(plan_dir or os.getenv('SLACK_SYNC_PLAN_DIR', 'handover_runs/work20'))
    if (folder / 'pending.json').exists():
        raise ValueError('An unfinished sync plan exists; reconcile it before retrying to avoid duplicate writes')
    if raw.get('work_id') != WORK_ID or not raw.get('records'):
        raise ValueError('No WORK-00020 messages found within the collection window; DB unchanged')
    allowed = {(t['channel_id'], t['thread_ts']) for t in threads}
    for row in raw['records']:
        root = row.get('parent_ts') or row['slack_ts']
        if (row['conversation_id'], root) not in allowed:
            raise ValueError('MCP returned messages outside WORK-00020')
    messages = normalize_messages(raw)
    previous = prior_messages(store, threads)
    deleted = {mid for mid, row in previous.items()
               if row.get('slack_ts') and float(row['slack_ts']) >= raw['metadata']['oldest_ts']} - {m['source_id'] for m in messages}
    if deleted:
        raise ValueError('Previously stored Slack messages are missing; reconcile deletion before syncing')
    changed = [m for m in messages if m['source_id'] not in previous
               or previous[m['source_id']].get('text') != m['raw_text']
               or previous[m['source_id']].get('author_id') != m['slack_id']]
    if not changed:
        return {'work_id': WORK_ID, 'messages': len(messages), 'changed_messages': 0,
                'saved': True, 'llm_executed': False, 'tasks': len(scope['tasks']),
                'events': len(scope['events'])}
    if not os.getenv('OPENAI_API_KEY'):
        raise ValueError('OPENAI_API_KEY is required to extract changed Slack messages; DB unchanged')
    store.preflight_raw_message_schema()
    known = {p['person_id']: {'slack_id': p['person_id'], 'name': p['name']} for p in scope['persons']}
    known.update({p['slack_id']: p for p in raw['people']})
    data = {**raw, 'people': list(known.values())}
    folder.mkdir(parents=True, exist_ok=True)
    previous_result = {}
    if (folder / 'last.json').exists():
        previous_result = json.loads((folder / 'last.json').read_text())
    result = run(data, snapshot=scope, prior_result=previous_result,
                 event_cache_dir=folder / 'event_cache')
    if {w['work_id'] for w in result['works']} != {WORK_ID}:
        raise ValueError('Extraction did not preserve WORK-00020; DB unchanged')
    bundle, warnings = to_db(result, before)
    if identity_conflicts(bundle, before):
        raise ValueError('Slack names conflict with existing person IDs; DB unchanged')
    # Shared Tasks/Events were rejected above; LLM output may only reuse this scope.
    for table, key in [('tasks', 'task_id'), ('events', 'event_id')]:
        outside = {row[key] for row in before[table]} - {row[key] for row in scope[table]}
        if any(row[key] in outside for row in bundle[table]):
            raise ValueError('Extraction attempted to update another Work; DB unchanged')
    if digest(store.snapshot()) != digest(before):
        raise ValueError('DB changed during extraction; retry against a fresh snapshot')
    plan = {'before_digest': digest(before), 'result': result, 'bundle': bundle, 'warnings': warnings}
    (folder / 'pending.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    store.save(bundle, before)
    store.save_messages(result['messages'], result['people'])
    # Read back actual stored rows before reporting success.
    after = store.snapshot()
    for table, rows in bundle.items():
        keys = TABLE_KEYS[table].split(',')
        index = lambda row: tuple(row[key] for key in keys)
        saved = {index(row): row for row in after[table]}
        for row in rows:
            actual = saved.get(index(row))
            if actual is None:
                raise RuntimeError('DB sync verification failed: ' + table)
            for key, expected in row.items():
                value = actual.get(key)
                if key in {'due_at', 'deadline_at', 'updated_at'} and value and expected:
                    from datetime import datetime
                    equal = datetime.fromisoformat(value.replace('Z', '+00:00')) == datetime.fromisoformat(expected.replace('Z', '+00:00'))
                else:
                    equal = value == expected
                if not equal:
                    raise RuntimeError('DB sync verification failed: ' + table + '.' + key)
    saved_messages = prior_messages(store, threads)
    if any(saved_messages.get(m['source_id'], {}).get('text') != m['raw_text'] for m in messages):
        raise RuntimeError('Slack raw message verification failed')
    (folder / 'last.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (folder / 'pending.json').unlink()
    return {'work_id': WORK_ID, 'messages': len(messages), 'changed_messages': len(changed),
            'saved': True, 'llm_executed': True, 'tasks': len(result['tasks']),
            'events': len(result['events']), 'warnings': len(warnings)}
