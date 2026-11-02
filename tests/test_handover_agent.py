"""Exercise the existing approval record contract without changing the DB."""
import os
import sys
import types
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from src.agent_db_chat import DBChatRequest, approved_handover, ask_db_agent
from test_agent_db_chat import fixture


class HandoverAgentTest(unittest.TestCase):
    def setUp(self):
        self.store = fixture()
        self.row = {'requester_id': 'U999', 'work_id': 'WORK-20', 'status': 'pending'}
        self.lookup = Mock(side_effect=self.read_approval)
        # The production helper imports this existing reader lazily; isolate
        # the large server module, not the authorization function under test.
        module = types.ModuleType('src.demo_frontend')
        module._handover_db = self.lookup
        self.patches = [
            patch.dict(sys.modules, {'src.demo_frontend': module}),
            patch.dict(os.environ, {'API_ACCESS_TOKEN': 'test', 'AGENT_DB_ENABLED': '1',
                                    'OPENAI_API_KEY': 'fake'}, clear=True),
            patch('src.agent_db_chat.verified_actor', return_value={'person_id': 'U999'}),
            patch('src.agent_db_chat.configured_stores', return_value=(self.store, self.store)),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.model = patch('src.agent_db_chat.call_text', return_value=('확인 요청이 남아 있습니다. [S1]', {})).start()
        self.addCleanup(patch.stopall)
        self.request = DBChatRequest(question='다음 할 일은?', task_id='TASK-00080')

    def read_approval(self, *, params):
        self.assertEqual(params, {'select': 'requester_id,work_id,status',
                                 'requester_id': 'eq.U999', 'work_id': 'eq.WORK-20',
                                 'status': 'eq.approved', 'limit': 1})
        return [dict(self.row)] if all(str(self.row[k]) == params[k][3:]
                                      for k in ('requester_id', 'work_id', 'status')) else []

    def ask(self):
        return ask_db_agent(self.request, None, 'Bearer test')

    def assert_denied(self):
        self.store.calls.clear()
        self.model.reset_mock()
        with self.assertRaises(HTTPException) as caught:
            self.ask()
        self.assertEqual(caught.exception.status_code, 403)
        self.assertFalse(any(t in ('tasks', 'slack_messages') for t, _ in self.store.calls))
        self.model.assert_not_called()

    def test_pending_approved_then_rejected_is_checked_every_question(self):
        self.assert_denied()
        self.row['status'] = 'approved'
        result = self.ask()
        self.assertTrue(result['llm_called'])
        self.assertEqual(result['sources'][0]['task_id'], 'TASK-00080')
        self.row['status'] = 'rejected'
        self.assert_denied()
        self.assertEqual(self.lookup.call_count, 3)

    def test_other_receiver_or_other_work_does_not_grant_access(self):
        self.row['status'] = 'approved'
        for field, value in [('requester_id', 'U777'), ('work_id', 'WORK-OTHER')]:
            with self.subTest(field=field), patch.dict(self.row, {field: value}):
                self.assert_denied()

    def test_unexpected_storage_rows_are_rechecked(self):
        self.lookup.side_effect = None
        for changed in [{'status': 'pending'}, {'requester_id': 'U777'}, {'work_id': 'WORK-OTHER'}]:
            self.lookup.return_value = [{**self.row, 'status': 'approved', **changed}]
            self.assertFalse(approved_handover('U999', 'WORK-20'))

    def test_approval_storage_error_never_calls_model(self):
        self.lookup.side_effect = HTTPException(502, 'Handover database unreachable')
        with self.assertRaises(HTTPException) as caught:
            self.ask()
        self.assertEqual(caught.exception.status_code, 502)
        self.model.assert_not_called()
        self.assertFalse(any(t in ('tasks', 'slack_messages') for t, _ in self.store.calls))


if __name__ == '__main__':
    unittest.main()
