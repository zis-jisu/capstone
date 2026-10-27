import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from src.handover_catalog import handover_catalog
from src import demo_frontend as api


def data():
    return {'persons': [{'person_id': 'JISOO', 'name': '김지수'}],
            'works': [{'work_id': 'WORK-00020', 'title': '신차 캠페인'}, {'work_id': 'OTHER', 'title': '다른 업무'}],
            'tasks': [{'task_id': 'T1', 'title': '원본 확인', 'status': 'completed'},
                      {'task_id': 'T2', 'title': '원고 확정', 'status': 'in_progress'},
                      {'task_id': 'T3', 'title': '다른 업무', 'status': 'waiting'}],
            'events': [{'event_id': 'E1', 'evidence': '비공개 원문'}],
            'edges': [
                {'source_id': 'JISOO', 'source_type': 'Person', 'target_id': 'T2', 'target_type': 'Task', 'relation': 'REVIEWER'},
                {'source_id': 'WORK-00020', 'source_type': 'Work', 'target_id': 'T1', 'target_type': 'Task', 'relation': 'HAS_TASK'},
                {'source_id': 'WORK-00020', 'source_type': 'Work', 'target_id': 'T2', 'target_type': 'Task', 'relation': 'HAS_TASK'},
                {'source_id': 'OTHER', 'source_type': 'Work', 'target_id': 'T3', 'target_type': 'Task', 'relation': 'HAS_TASK'}]}


class CatalogTests(unittest.TestCase):
    def test_reviewer_can_request_whole_work(self):
        rows = handover_catalog(data(), 'JISOO')
        self.assertEqual([w['work_id'] for w in rows], ['WORK-00020'])
        self.assertEqual([t['task_id'] for t in rows[0]['tasks']], ['T1', 'T2'])

    def test_collaborator_also_included(self):
        snapshot = data();snapshot['edges'][0]['relation'] = 'COLLABORATOR'
        self.assertEqual(handover_catalog(snapshot, 'JISOO')[0]['work_id'], 'WORK-00020')

    def test_unrelated_person_has_no_works(self):
        self.assertEqual(handover_catalog(data(), 'UNKNOWN'), [])

    def test_catalog_contains_no_event_evidence(self):
        api.app.dependency_overrides[api.demo_auth] = lambda: True
        api.app.dependency_overrides[api.slack_actor] = lambda: None
        try:
            with patch.object(api, '_hybrid_frontend_snapshot', return_value=data()):
                response = TestClient(api.app).get('/api/demo/handover-catalog?source_person_id=JISOO')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['works'][0]['work_id'], 'WORK-00020')
            self.assertNotIn('비공개 원문', response.text)
            self.assertNotIn('events', response.json())
        finally:
            api.app.dependency_overrides.clear()
