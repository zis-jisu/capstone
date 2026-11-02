import base64
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from src.agent_db_chat import DemoDBChatRequest, ask_demo_db_agent, chat_config
from test_agent_db_chat import fixture


class DemoDBChatTest(unittest.TestCase):
    def setUp(self):
        self.auth = 'Basic ' + base64.b64encode(b'demo:password').decode()
        self.req = DemoDBChatRequest(question='상태와 원문은?', task_id='TASK-00080', demo_person_id='U0C20G9MRML')
        self.env = {'DEMO_USERNAME': 'demo', 'DEMO_PASSWORD': 'password', 'AGENT_DB_DEMO_ENABLED': '1',
                    'AGENT_DB_DEMO_DATA_VERIFIED': '1', 'AGENT_DB_DEMO_TASK_IDS': 'TASK-00080',
                    'OPENAI_API_KEY': 'test'}

    def test_shared_login_and_allowlisted_demo_data_work_without_slack_login(self):
        store = fixture()
        store.tables['edges'][0]['source_id'] = self.req.demo_person_id
        with patch.dict(os.environ, self.env, clear=True), patch('src.agent_db_chat.configured_stores', return_value=(store, store)), patch('src.agent_db_chat.call_text', return_value=('이미지 작업 완료 [S1]', {})), patch('src.agent_db_chat.verified_actor') as actor:
            result = ask_demo_db_agent(self.req, self.auth)
        self.assertEqual(result['mode'], 'db_slack_demo')
        self.assertFalse(result['identity_verified'])
        self.assertTrue(result['sources'])
        actor.assert_not_called()

    def test_non_allowlisted_task_is_denied_before_lookup(self):
        self.req.task_id = 'TASK-00079'
        with patch.dict(os.environ, self.env, clear=True), patch('src.agent_db_chat.configured_stores') as stores:
            with self.assertRaises(HTTPException) as caught:
                ask_demo_db_agent(self.req, self.auth)
            self.assertEqual(caught.exception.status_code, 403)
            stores.assert_not_called()

    def test_unreviewed_scope_or_disabled_mode_cannot_read_db(self):
        for field in ['AGENT_DB_DEMO_ENABLED', 'AGENT_DB_DEMO_DATA_VERIFIED', 'AGENT_DB_DEMO_TASK_IDS']:
            with self.subTest(field=field), patch.dict(os.environ, {**self.env, field: ''}, clear=True), patch('src.agent_db_chat.configured_stores') as stores:
                with self.assertRaises(HTTPException) as caught:
                    ask_demo_db_agent(self.req, self.auth)
                self.assertEqual(caught.exception.status_code, 503)
                stores.assert_not_called()

    def test_bearer_cannot_impersonate_shared_basic_login(self):
        with patch.dict(os.environ, {**self.env, 'API_ACCESS_TOKEN': 't'}, clear=True):
            with self.assertRaises(HTTPException) as caught:
                ask_demo_db_agent(self.req, 'Bearer t')
        self.assertEqual(caught.exception.status_code, 401)

    def test_demo_role_relationship_still_checked(self):
        with patch.dict(os.environ, self.env, clear=True), patch('src.agent_db_chat.configured_stores', return_value=(fixture(), fixture())):
            with self.assertRaises(HTTPException) as caught:
                ask_demo_db_agent(self.req, self.auth)
        self.assertEqual(caught.exception.status_code, 403)

    def test_configuration_routes_only_explicitly_enabled_demo(self):
        import json
        with patch.dict(os.environ, self.env, clear=True):
            result = json.loads(chat_config(self.auth).body)
        self.assertEqual(result['endpoint'], '/api/chat/db/demo')
        self.assertFalse(result['identity_verified'])


if __name__ == '__main__':
    unittest.main()
