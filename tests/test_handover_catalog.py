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
            with patch('src.handover_catalog.load_catalog_snapshot', return_value=data()), patch.object(api, '_frontend_store'), patch.object(api, 'SupabaseStore'):
                response = TestClient(api.app).get('/api/demo/handover-catalog?source_person_id=JISOO')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['works'][0]['work_id'], 'WORK-00020')
            self.assertNotIn('비공개 원문', response.text)
            self.assertNotIn('events', response.json())
        finally:
            api.app.dependency_overrides.clear()


class MetadataQueryTests(unittest.TestCase):
    def test_catalog_never_queries_events_or_message_bodies(self):
        from unittest.mock import Mock
        from src.handover_catalog import load_catalog_snapshot
        snapshot = data()
        def request(table, params):
            self.assertNotIn(table, {'events', 'slack_messages'})
            fields = params['select'].split(',')
            return [{key: row[key] for key in fields if key in row} for row in snapshot[table]]
        stores = [Mock(), Mock()]
        for store in stores:
            store.request.side_effect = request
        result = load_catalog_snapshot(*stores, 'JISOO', api._overlay_original_work)
        works = handover_catalog(result, 'JISOO')
        self.assertEqual(works[0]['work_id'], 'WORK-00020')
        self.assertEqual(len(works[0]['tasks']), 2)
        self.assertEqual(result['events'], [])
