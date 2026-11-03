import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from src.agent_chat import ChatRequest, ask_agent


class WorkScopeTest(unittest.TestCase):
    def setUp(self):
        # Synthetic fixtures keep tests portable without publishing account data.
        self.snapshot = {
            'question': '선택한 업무만 보지 말고, 조회 가능한 전체 Work 중 우선순위가 가장 높은 Work의 이름과 점수를 알려줘. 전체 목록을 확인할 수 없다면 그 한계도 알려줘.',
            'tasks': [
                {'task_id': f'TASK-{i:05d}', 'name': f'테스트 업무 {i}',
                 'status': '진행 중', 'priority_score': None, 'priority_rank': None}
                for i in range(21, 35)
            ] + [{'task_id': 'TASK-00103', 'name': '테스트 최우선 Task',
                  'status': '대기', 'priority_score': 95.5, 'priority_rank': 1}],
        }

    def request(self, question):
        return ChatRequest(question=question, task_id='TASK-00022', tasks=self.snapshot['tasks'])

    def test_original_live_failure_is_blocked_without_llm_or_api_key(self):
        with patch.dict(os.environ, {'API_ACCESS_TOKEN': 'test-token'}, clear=True), patch('src.agent_chat.call_text') as call:
            result = ask_agent(self.request(self.snapshot['question']), 'Bearer test-token')
        call.assert_not_called()
        self.assertFalse(result['llm_called'])
        self.assertIsNone(result['model'])
        self.assertEqual(result['sources'], [])
        self.assertIn('확인할 수 없습니다', result['answer'])
        self.assertNotIn('95.5', result['answer'])

    def test_explicit_work_variants(self):
        questions = ['전체 Work 중 1위는?', 'work 우선순위 알려줘', 'WORKS 중 가장 급한 것은?',
                     '워크 순위 알려줘', '1순위 Work의 이름과 점수는?']
        for question in questions:
            with self.subTest(question=question), patch.dict(os.environ, {'API_ACCESS_TOKEN': 't'}, clear=True):
                result = ask_agent(self.request(question), 'Bearer t')
                self.assertEqual(result['answer_type'], 'insufficient_work_context')

    def test_auth_is_required_even_for_work_limitation(self):
        with patch.dict(os.environ, {'API_ACCESS_TOKEN': 't'}, clear=True):
            with self.assertRaises(HTTPException) as caught:
                ask_agent(self.request('Work 순위는?'), 'Bearer wrong')
        self.assertEqual(caught.exception.status_code, 401)

    def test_unrelated_words_do_not_block_task_questions(self):
        for question in ['네트워크 점검 업무 상태는?', '워크플로 수정의 담당자는?',
                         'framework 배포 상태 알려줘', 'homework 마감은?',
                         '멀티태스크 작업 상태 알려줘']:
            with self.subTest(question=question), patch.dict(os.environ, {'API_ACCESS_TOKEN': 't', 'OPENAI_API_KEY': 'fake'}, clear=True), patch('src.agent_chat.call_text', return_value=('테스트 답변', {})) as call:
                result = ask_agent(self.request(question), 'Bearer t')
                call.assert_called_once()
                self.assertEqual(result['answer'], '테스트 답변')

    def test_korean_entity_particles(self):
        for question in ['워크의 점수는?', '워크별로 순위를 알려줘', '워크들 중 가장 급한 것은?', '워크에서는 누가 담당이야?']:
            with self.subTest(question=question), patch.dict(os.environ, {'API_ACCESS_TOKEN': 't'}, clear=True), patch('src.agent_chat.call_text') as call:
                result = ask_agent(self.request(question), 'Bearer t')
                call.assert_not_called()
                self.assertEqual(result['answer_type'], 'insufficient_work_context')

    def test_korean_mixed_question_keeps_task_part_available(self):
        for question in ['워크와 태스크의 순위를 각각 알려줘', '워크의 점수와 테스크의 담당자를 알려줘']:
            with self.subTest(question=question), patch.dict(os.environ, {'API_ACCESS_TOKEN': 't', 'OPENAI_API_KEY': 'fake'}, clear=True), patch('src.agent_chat.call_text', return_value=('테스트 답변', {})) as call:
                ask_agent(self.request(question), 'Bearer t')
                call.assert_called_once()

    def test_task_and_mixed_questions_keep_current_context_and_llm_path(self):
        for question in ['전체 Task 1위는?', '현재 업무 상태는?', 'Work와 Task를 구분해서 알려줘']:
            with self.subTest(question=question), patch.dict(os.environ, {'API_ACCESS_TOKEN': 't', 'OPENAI_API_KEY': 'fake'}, clear=True), patch('src.agent_chat.call_text', return_value=('테스트 답변', {})) as call:
                result = ask_agent(self.request(question), 'Bearer t')
                call.assert_called_once()
                context = call.call_args.kwargs['user_payload']['context']
                self.assertEqual(context['entity_type'], 'Task')
                self.assertFalse(context['work_context_available'])
                self.assertEqual(len(context['tasks']), 15)
                self.assertEqual(context['selected_task']['task_id'], 'TASK-00022')
                self.assertEqual(result['answer'], '테스트 답변')

    def test_unknown_selected_task_still_rejected(self):
        request = self.request('Work 순위는?')
        request.task_id = 'TASK-99999'
        with patch.dict(os.environ, {'API_ACCESS_TOKEN': 't'}, clear=True):
            with self.assertRaises(HTTPException) as caught:
                ask_agent(request, 'Bearer t')
        self.assertEqual(caught.exception.status_code, 400)


if __name__ == '__main__':
    unittest.main()
