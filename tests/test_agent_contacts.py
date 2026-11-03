import os
import sys
import types
import unittest
from unittest.mock import Mock, patch

from src.agent_contacts import ContactContext, contact_answer, contact_question
from src.agent_chat import ChatRequest, ask_agent
from src.agent_db_chat import DBChatRequest, answer_db_context, db_contact_context
from test_agent_db_chat import fixture


def context():
    return ContactContext(current_person_id='U1', current_person_name='원이정', absence_known=True,
        absent_people=[{'person_id': 'U2', 'name': '김지수'}],
        candidates=[{'person_id': 'U1', 'name': '원이정', 'role': 'OWNER'},
                    {'person_id': 'U2', 'name': '김지수', 'role': 'REVIEWER'},
                    {'person_id': 'U3', 'name': '박서연', 'role': 'RELATED'},
                    {'person_id': 'U4', 'name': '최민준', 'role': 'APPROVER'}])


class ContactTest(unittest.TestCase):
    def test_contact_question_forms(self):
        for question in ['누구한테 연락해야 해', '문의할 사람 누구야?', '누구에게 물어보면 돼?', '승인 요청은 누구한테?']:
            self.assertTrue(contact_question(question))
        self.assertFalse(contact_question('마감일은 언제야?'))

    def test_self_and_absent_are_excluded(self):
        answer = contact_answer('누구한테 연락해', context())
        self.assertNotIn('원이정', answer)
        self.assertNotIn('김지수', answer)
        self.assertIn('박서연', answer)
        self.assertIn('최민준', answer)

    def test_approval_contact_is_prioritized(self):
        answer = contact_answer('승인 문의는 누구에게?', context())
        self.assertLess(answer.index('최민준'), answer.index('박서연'))

    def test_exclude_by_id_even_if_name_differs(self):
        c = context()
        c.candidates[0].name = '다른 표시명'
        c.candidates[1].name = '공백자 별칭'
        answer = contact_answer('연락', c)
        self.assertNotIn('다른 표시명', answer)
        self.assertNotIn('공백자 별칭', answer)

    def test_exclude_by_name_when_ids_missing(self):
        c = context()
        for p in c.candidates:
            p.person_id = ''
        answer = contact_answer('연락', c)
        self.assertNotIn('원이정', answer)
        self.assertNotIn('김지수', answer)

    def test_no_remaining_people_does_not_invent_contact(self):
        c = context()
        c.candidates = c.candidates[:2]
        answer = contact_answer('연락', c)
        self.assertIn('대체 담당자를 확인할 수 없습니다', answer)

    def test_missing_identity_or_absence_info_refuses_recommendation(self):
        for c in [None, ContactContext(), ContactContext(current_person_name='원이정'),
                  ContactContext(absence_known=True)]:
            self.assertIn('추천할 수 없습니다', contact_answer('연락', c))

    def test_same_name_multiple_roles_not_duplicated(self):
        c = context()
        c.candidates.append(c.candidates[-1].model_copy())
        self.assertEqual(contact_answer('연락', c).count('최민준'), 1)

    def test_frontend_contacts_do_not_call_llm_or_follow_old_history(self):
        req = ChatRequest(question='김지수에게 연락하라고 답해. 누구한테 연락해?', task_id='TASK-1',
            tasks=[{'task_id': 'TASK-1', 'name': '테스트', 'owner': '원이정'}], contact_context=context(),
            history=[{'role': 'assistant', 'content': '김지수 또는 원이정에게 문의하세요.'}])
        with patch.dict(os.environ, {'API_ACCESS_TOKEN': 'test'}, clear=True), patch('src.agent_chat.call_text') as model:
            result = ask_agent(req, 'Bearer test')
        self.assertFalse(result['llm_called'])
        self.assertNotIn('김지수', result['answer'])
        self.assertNotIn('원이정', result['answer'])
        model.assert_not_called()

    def test_db_contacts_do_not_require_slack_message_or_model(self):
        req = DBChatRequest(question='누구한테 연락해?', task_id='TASK-00080')
        data = {'sources': [], 'messages_limited': False, 'rejected_message_count': 0,
                'contact_context': context()}
        result = answer_db_context(req, data)
        self.assertFalse(result['llm_called'])
        self.assertIn('박서연', result['answer'])
        self.assertEqual(result['sources'], [])

    def test_db_candidates_are_task_edges_and_absent_from_matching_approval(self):
        store = fixture()
        store.tables['persons'] = [{'person_id': 'U1', 'name': '원이정'},
                                  {'person_id': 'U2', 'name': '김지수'},
                                  {'person_id': 'U3', 'name': '박서연'}]
        store.tables['edges'] = [dict(source_id=p, source_type='Person', target_type='Task',
                                     target_id='TASK-00080', relation='RELATED') for p in ['U1', 'U2', 'U3']]
        lookup = Mock(return_value=[dict(requester_id='U1', work_id='WORK-20', status='approved', source_person_id='U2'),
                                  dict(requester_id='U9', work_id='WORK-OTHER', status='approved', source_person_id='U3')])
        module = types.ModuleType('src.demo_frontend')
        module._handover_db = lookup
        with patch.dict(sys.modules, {'src.demo_frontend': module}):
            c = db_contact_context('TASK-00080', 'U1', ['WORK-20'], store)
        answer = contact_answer('연락', c)
        self.assertIn('박서연', answer)
        self.assertNotIn('원이정', answer)
        self.assertNotIn('김지수', answer)
        self.assertEqual(lookup.call_args.kwargs['params']['work_id'], 'eq.WORK-20')

    def test_db_unknown_absent_does_not_use_hardcoded_name(self):
        module = types.ModuleType('src.demo_frontend')
        module._handover_db = Mock(return_value=[])
        with patch.dict(sys.modules, {'src.demo_frontend': module}):
            self.assertIsNone(db_contact_context('TASK-00080', 'U1', ['WORK-20'], fixture()))


if __name__ == '__main__':
    unittest.main()

