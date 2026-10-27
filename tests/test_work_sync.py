import copy
import json
import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch
from fastapi.testclient import TestClient
from fastapi.responses import StreamingResponse
from src.slack.mcp_server import collect_work_context, make_server
from src.work_sync import work_scope, evidence_threads, apply_collection
from src import demo_frontend as api


def snapshot():
    return {'persons': [{'person_id': 'U1', 'name': '작성자'}],
            'works': [{'work_id': 'WORK-00020', 'title': '캠페인'}, {'work_id': 'WORK-OTHER', 'title': '다른 업무'}],
            'tasks': [{'task_id': 'TASK-1', 'title': '원고', 'status': 'waiting'}, {'task_id': 'TASK-OTHER'}],
            'events': [{'event_id': 'E1', 'source_id': 'C1:100.000001', 'conversation_id': 'C1',
                        'parent_ts': None, 'evidence': '원고 확인'}],
            'edges': [
                {'source_id': 'WORK-00020', 'source_type': 'Work', 'relation': 'HAS_TASK', 'target_id': 'TASK-1', 'target_type': 'Task'},
                {'source_id': 'WORK-OTHER', 'source_type': 'Work', 'relation': 'HAS_TASK', 'target_id': 'TASK-OTHER', 'target_type': 'Task'},
                {'source_id': 'TASK-1', 'source_type': 'Task', 'relation': 'HAS_EVENT', 'target_id': 'E1', 'target_type': 'Event'},
                {'source_id': 'U1', 'source_type': 'Person', 'relation': 'OWNER', 'target_id': 'TASK-1', 'target_type': 'Task'}]}


def raw(text='원고 확인'):
    return {'work_id': 'WORK-00020', 'people': [{'slack_id': 'U1', 'name': '작성자'}],
            'records': [{'source_id': 'C1:100.000001', 'conversation_id': 'C1', 'slack_ts': '100.000001',
                         'slack_author_id': 'U1', 'raw_text': text, 'parent_ts': None}],
            'metadata': {'oldest_ts': 0, 'days': 90}}


class CollectionTests(unittest.TestCase):
    def test_pagination_window_and_mentions(self):
        now = time.time()
        root = f'{now-20*86400:.6f}'  # outside 14 days, inside 90 days
        calls = []
        def get(method, params):
            calls.append((method, params))
            if method == 'users.info':
                return {'user': {'real_name': params['user']}}
            if params.get('cursor'):
                return {'messages': [{'ts': f'{now-1:.6f}', 'thread_ts': root, 'user': 'U2', 'text': '완료'}]}
            return {'messages': [{'ts': root, 'user': 'U1', 'text': '<@U3|검토자> 확인'},
                                 {'ts': f'{now-100*86400:.6f}', 'user': 'U1', 'text': '기간 밖'}],
                    'has_more': True, 'response_metadata': {'next_cursor': 'next'}}
        with patch('src.slack.mcp_server._get', side_effect=get):
            result = collect_work_context('WORK-00020', [{'channel_id': 'C1', 'thread_ts': root}])
        self.assertEqual(len(result['records']), 2)
        self.assertEqual(result['metadata']['days'], 90)
        self.assertEqual({p['slack_id'] for p in result['people']}, {'U1', 'U2', 'U3'})
        self.assertTrue(all(method != 'conversations.history' for method, _ in calls))
        self.assertEqual(result['records'][1]['parent_ts'], root)

    def test_reject_other_work(self):
        with self.assertRaises(ValueError):
            collect_work_context('WORK-OTHER', [{'channel_id': 'C1', 'thread_ts': '100.000001'}])

    def test_incomplete_page_is_not_success(self):
        with patch('src.slack.mcp_server._get', return_value={'messages': [], 'has_more': True}):
            with self.assertRaises(RuntimeError):
                collect_work_context('WORK-00020', [{'channel_id': 'C1', 'thread_ts': '100.000001'}])


class SyncTests(unittest.TestCase):
    def test_scope_and_roots_exclude_other_work(self):
        scope = work_scope(snapshot())
        self.assertEqual([t['task_id'] for t in scope['tasks']], ['TASK-1'])
        self.assertEqual(evidence_threads(scope), [{'channel_id': 'C1', 'thread_ts': '100.000001'}])

    def test_shared_task_rejected(self):
        before = snapshot()
        before['edges'].append({**before['edges'][0], 'source_id': 'WORK-OTHER'})
        with self.assertRaises(ValueError):
            work_scope(before)

    def test_unchanged_skips_llm_and_writes(self):
        store, run = Mock(), Mock()
        store.request.return_value = [{'message_id': 'C1:100.000001', 'text': '원고 확인', 'author_id': 'U1', 'slack_ts': '100.000001'}]
        before = snapshot();scope = work_scope(before)
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            result = apply_collection(store, before, scope, raw(), evidence_threads(scope), run=run, plan_dir=folder)
        self.assertFalse(result['llm_executed']); self.assertEqual(result['changed_messages'], 0)
        run.assert_not_called(); store.save.assert_not_called(); store.save_messages.assert_not_called()

    def test_changed_missing_llm_key_has_no_writes(self):
        store = Mock();store.request.return_value = []
        before = snapshot();scope = work_scope(before)
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'OPENAI_API_KEY'):
                apply_collection(store, before, scope, raw(), evidence_threads(scope), plan_dir=folder)
        store.save.assert_not_called()

    def test_out_of_scope_record_is_rejected(self):
        before = snapshot();scope = work_scope(before);data = raw()
        data['records'][0]['conversation_id'] = 'COTHER'
        with tempfile.TemporaryDirectory() as folder, self.assertRaisesRegex(ValueError, 'outside'):
            apply_collection(Mock(), before, scope, data, evidence_threads(scope), plan_dir=folder)

    def test_pending_plan_blocks_duplicate_retry(self):
        from pathlib import Path
        before = snapshot();scope = work_scope(before)
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'pending.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'unfinished'):
                apply_collection(Mock(), before, scope, raw(), evidence_threads(scope), plan_dir=folder)

    def test_wrong_work_extraction_never_saved(self):
        store = Mock();store.request.return_value = []
        before = snapshot();scope = work_scope(before)
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'OPENAI_API_KEY': 'fake-test'}):
            with self.assertRaisesRegex(ValueError, 'preserve'):
                apply_collection(store, before, scope, raw(), evidence_threads(scope), plan_dir=folder,
                                 run=Mock(return_value={'works': [{'work_id': 'WORK-OTHER'}]}))
        store.save.assert_not_called()

    def test_changed_sync_writes_and_verifies_without_touching_other_work(self):
        from src.pipeline import normalize_messages
        from src.db import TABLE_KEYS
        before = snapshot(); scope = work_scope(before); data = raw()
        event = {'event_id': 'E1', 'source_id': 'C1:100.000001', 'evidence': '원고 확인',
                 'actor': {'slack_id': 'U1', 'name': '작성자'}, 'event_type': 'update'}
        result = {'people': data['people'], 'messages': normalize_messages(data), 'events': [event],
                  'tasks': [{'task_id': 'TASK-1', 'title': '원고', 'status': 'in_progress',
                             'events': [{'event_id': 'E1'}]}],
                  'works': [{'work_id': 'WORK-00020', 'title': '캠페인', 'tasks': [{'task_id': 'TASK-1'}]}]}
        store = Mock(); current = copy.deepcopy(before); messages = {}
        store.snapshot.side_effect = lambda: copy.deepcopy(current)
        store.request.side_effect = lambda *a, **kw: list(messages.values())
        def save(bundle, old):
            for table, rows in bundle.items():
                keys = TABLE_KEYS[table].split(',')
                key = lambda r: tuple(r[k] for k in keys)
                index = {key(row): row for row in current[table]}
                index.update({key(row): copy.deepcopy(row) for row in rows})
                current[table] = list(index.values())
        store.save.side_effect = save
        def save_messages(rows, people):
            messages.update({m['source_id']: {'message_id': m['source_id'], 'text': m['raw_text']} for m in rows})
        store.save_messages.side_effect = save_messages
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'OPENAI_API_KEY': 'fake-test'}):
            response = apply_collection(store, before, scope, data, evidence_threads(scope),
                                        plan_dir=folder, run=Mock(return_value=result))
            from pathlib import Path
            self.assertTrue(Path(folder, 'last.json').exists())
            self.assertFalse(Path(folder, 'pending.json').exists())
        self.assertTrue(response['saved']); self.assertTrue(response['llm_executed'])
        self.assertEqual(response['changed_messages'], 1)
        self.assertEqual(next(w for w in current['works'] if w['work_id'] == 'WORK-OTHER'), before['works'][1])
        self.assertEqual(next(t for t in current['tasks'] if t['task_id'] == 'TASK-OTHER'), before['tasks'][1])


class EndpointTests(unittest.TestCase):
    def setUp(self):
        api.app.dependency_overrides[api.admin_auth] = lambda: True
        api._work_sync_task = None
        self.client = TestClient(api.app)

    def tearDown(self):
        api.app.dependency_overrides.clear()

    def test_missing_slack_token_fails_before_stream(self):
        with patch.dict(os.environ, {}, clear=True):
            response = self.client.post('/api/demo/slack-link')
        self.assertEqual(response.status_code, 503)

    def test_only_work20_accepted(self):
        self.assertEqual(self.client.post('/api/demo/slack-link', json={'work_id': 'WORK-OTHER'}).status_code, 422)
        self.assertEqual(self.client.post('/api/demo/slack-link', json={'days': 91}).status_code, 422)

    def test_full_endpoint_passes_90_days_and_streams_stages(self):
        store = Mock();store.snapshot.return_value = snapshot()
        saved = {'saved': True, 'messages': 1, 'changed_messages': 0}
        async def training():
            yield b'{"status":"completed"}\n'
        with patch.dict(os.environ, {'SLACK_TOKEN': 'fake-test'}), \
             patch.object(api, 'SupabaseStore', return_value=store), \
             patch.object(api, '_call_slack_mcp', new_callable=AsyncMock, return_value=raw()) as mcp, \
             patch('src.work_sync.apply_collection', return_value=saved), \
             patch('scripts.export_ml_rpc.fetch_graph', return_value={'nodes': [{'id': 'WORK-00020'}]}), \
             patch.object(api.ml_bridge, 'stream_training', return_value=StreamingResponse(training())):
            response = self.client.post('/api/demo/slack-link')
        events = [json.loads(line) for line in response.text.splitlines()]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(events[-1]['status'], 'completed')
        self.assertEqual(mcp.call_args.args[0], 'collect_slack_work_threads')
        self.assertEqual(mcp.call_args.args[1]['days'], 90)
        self.assertEqual([e['stage'] for e in events], ['collect', 'extract', 'saved', 'completed'])

    def test_mcp_failure_never_starts_training(self):
        store = Mock();store.snapshot.return_value = snapshot()
        with patch.dict(os.environ, {'SLACK_TOKEN': 'fake-test'}), \
             patch.object(api, 'SupabaseStore', return_value=store), \
             patch.object(api, '_call_slack_mcp', new_callable=AsyncMock, side_effect=RuntimeError('failure')), \
             patch.object(api.ml_bridge, 'stream_training') as training:
            response = self.client.post('/api/demo/slack-link')
        self.assertEqual(json.loads(response.text.splitlines()[-1])['status'], 'failed')
        training.assert_not_called();store.save.assert_not_called()
