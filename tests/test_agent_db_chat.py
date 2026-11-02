import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from src.agent_db_chat import DBChatRequest, ask_db_agent, configured_stores, read_task_messages


class MemoryStore:
    def __init__(self, tables):
        self.tables = tables
        self.calls = []

    def request(self, table, *, params=None, method='GET', rows=None):
        assert method == 'GET' and rows is None, 'No writes allowed'
        self.calls.append((table, params))
        selected = list(self.tables.get(table, []))
        for key, value in (params or {}).items():
            if isinstance(value, str) and value.startswith('eq.'):
                selected = [r for r in selected if str(r.get(key)) == value[3:]]
        if table == 'edges' and params.get('relation', '').startswith('in.'):
            allowed = params['relation'][4:-1].split(',')
            selected = [r for r in selected if r.get('relation') in allowed]
        if table == 'slack_messages':
            selected.sort(key=lambda r: r.get('slack_ts') or '', reverse=True)
        return selected[:params.get('limit', len(selected))]


def fixture():
    return MemoryStore({
        'tasks': [{'task_id': 'TASK-00080', 'title': '테스트 배포 준비', 'status': 'waiting'}],
        'edges': [
            {'source_id': 'U123', 'source_type': 'Person', 'target_id': 'TASK-00080',
             'target_type': 'Task', 'relation': 'OWNER'},
            {'source_id': 'WORK-20', 'source_type': 'Work', 'target_id': 'TASK-00080',
             'target_type': 'Task', 'relation': 'HAS_TASK'},
        ],
        'slack_messages': [
            {'message_id': 'C123:1791289156.030089', 'task_id': 'TASK-00080',
             'work_id': 'WORK-20', 'author_name': '테스트 작성자', 'slack_ts': '1791289156.030089',
             'text': '자료를 준비하겠습니다.'},
            {'message_id': 'C123:1791289493.798879', 'task_id': 'TASK-00080',
             'work_id': 'WORK-20', 'author_name': '테스트 작성자', 'slack_ts': '1791289493.798879',
             'text': '이미지는 완료했고 링크 확인을 요청합니다.'},
            {'message_id': 'unrelated', 'task_id': None, 'work_id': 'WORK-20', 'text': '다른 문맥'},
        ],
    })


class DBRetrievalTest(unittest.TestCase):
    def test_table_names_must_be_configured_and_mixed_mapping_verified(self):
        for env in [{}, {'AGENT_DB_TASK_DATASET': 'mock', 'AGENT_DB_MESSAGE_DATASET': 'base'},
                    {'AGENT_DB_TASK_DATASET': 'anything', 'AGENT_DB_MESSAGE_DATASET': 'base'}]:
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                with self.assertRaises(HTTPException) as caught:
                    configured_stores()
                self.assertEqual(caught.exception.status_code, 503)

    def test_exact_task_only_and_newest_first(self):
        store = fixture()
        context = read_task_messages('TASK-00080', 'U123', store, store)
        self.assertEqual(len(context['sources']), 2)
        self.assertEqual(context['sources'][0]['message_id'], 'C123:1791289493.798879')
        self.assertEqual(context['sources'][0]['author_name'], '테스트 작성자')
        self.assertIsNotNone(context['sources'][0]['timestamp_utc'])
        query = store.calls[-1]
        self.assertEqual(query[0], 'slack_messages')
        self.assertEqual(query[1]['task_id'], 'eq.TASK-00080')
        self.assertNotIn('raw_json', query[1]['select'])

    def test_denied_before_reading_task_or_messages(self):
        store = fixture()
        with self.assertRaises(HTTPException) as caught:
            read_task_messages('TASK-00080', 'U999', store, store)
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual([t for t, _ in store.calls], ['edges'])

    def test_unrelated_role_is_not_permission(self):
        store = fixture()
        store.tables['edges'][0]['relation'] = 'RELATED'
        with self.assertRaises(HTTPException):
            read_task_messages('TASK-00080', 'U123', store, store)

    def test_wrong_work_link_is_rejected(self):
        store = fixture()
        store.tables['slack_messages'][0]['work_id'] = 'WORK-OTHER'
        result = read_task_messages('TASK-00080', 'U123', store, store)
        self.assertEqual(len(result['sources']), 1)
        self.assertEqual(result['rejected_message_count'], 1)

    def test_text_budget_and_limit_are_visible(self):
        store = fixture()
        store.tables['slack_messages'][0]['text'] = 'x' * 5000
        result = read_task_messages('TASK-00080', 'U123', store, store, limit=1)
        self.assertTrue(result['messages_limited'])
        result = read_task_messages('TASK-00080', 'U123', store, store)
        self.assertTrue(result['sources'][1]['text_truncated'])
        self.assertEqual(len(result['sources'][1]['text']), 4000)

    def test_filter_input_rejected_before_queries(self):
        store = fixture()
        with self.assertRaises(ValueError):
            read_task_messages('TASK-1,or=(task_id.neq.x)', 'U123', store, store)
        self.assertFalse(store.calls)


class DBChatTest(unittest.TestCase):
    def setUp(self):
        self.req = DBChatRequest(question='완료한 것과 다음 할 일은?', task_id='TASK-00080')
        self.env = {'API_ACCESS_TOKEN': 'test', 'AGENT_DB_ENABLED': '1', 'OPENAI_API_KEY': 'fake'}

    def invoke(self, store, answer='이미지는 완료했고 링크 확인이 필요합니다. [S1]'):
        with patch.dict(os.environ, self.env, clear=True), patch(
            'src.agent_db_chat.verified_actor', return_value={'person_id': 'U123'}
        ), patch('src.agent_db_chat.configured_stores', return_value=(store, store)), patch(
            'src.agent_db_chat.call_text', return_value=(answer, {})
        ) as call:
            result = ask_db_agent(self.req, None, 'Bearer test')
        return result, call

    def test_grounded_answer_uses_db_not_frontend(self):
        result, call = self.invoke(fixture())
        self.assertEqual(result['mode'], 'db_slack_task')
        self.assertEqual(len(result['sources']), 1)
        self.assertEqual(result['sources'][0]['id'], 'S1')
        context = call.call_args.kwargs['user_payload']['context']
        self.assertEqual(context['task']['status'], 'waiting')
        self.assertEqual(len(context['sources']), 2)

    def test_empty_evidence_does_not_call_model(self):
        store = fixture()
        store.tables['slack_messages'] = []
        result, call = self.invoke(store)
        self.assertEqual(result['answer_type'], 'no_slack_evidence')
        self.assertFalse(result['llm_called'])
        call.assert_not_called()

    def test_invalid_or_absent_citation_fails(self):
        for answer in ['근거 없음', '없는 출처 [S99]']:
            with self.subTest(answer=answer), self.assertRaises(HTTPException) as caught:
                self.invoke(fixture(), answer)
            self.assertEqual(caught.exception.status_code, 502)

    def test_shared_demo_login_is_not_person_authorization(self):
        with patch.dict(os.environ, self.env, clear=True), patch(
            'src.agent_db_chat.verified_actor', side_effect=HTTPException(401, 'Sign in')
        ), patch('src.agent_db_chat.configured_stores') as stores:
            with self.assertRaises(HTTPException) as caught:
                ask_db_agent(self.req, None, 'Bearer test')
            self.assertEqual(caught.exception.status_code, 401)
            stores.assert_not_called()

    def test_disabled_by_default(self):
        with patch.dict(os.environ, {'API_ACCESS_TOKEN': 'test'}, clear=True), patch(
            'src.agent_db_chat.verified_actor'
        ) as actor:
            with self.assertRaises(HTTPException) as caught:
                ask_db_agent(self.req, None, 'Bearer test')
            self.assertEqual(caught.exception.status_code, 503)
            actor.assert_not_called()

    def test_provider_errors_do_not_expose_details(self):
        with patch.dict(os.environ, self.env, clear=True), patch(
            'src.agent_db_chat.verified_actor', return_value={'person_id': 'U123'}
        ), patch('src.agent_db_chat.configured_stores', side_effect=RuntimeError('private URL/key')):
            with self.assertRaises(HTTPException) as caught:
                ask_db_agent(self.req, None, 'Bearer test')
        self.assertEqual(caught.exception.status_code, 502)
        self.assertNotIn('private', caught.exception.detail)


if __name__ == '__main__':
    unittest.main()
