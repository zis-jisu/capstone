import unittest
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from src import demo_frontend as api


def snapshot():
    return {'works': [{'work_id': x, 'title': x} for x in ['WORK-A', 'WORK-B', 'WORK-OTHER']],
            'tasks': [{'task_id': x} for x in ['TA', 'TB', 'TO']],
            'events': [{'event_id': 'E'+x, 'source_id': 'S'+x} for x in ['A', 'B', 'O']],
            'persons': [], 'edges': [edge for w, t, e in [('WORK-A','TA','EA'), ('WORK-B','TB','EB'), ('WORK-OTHER','TO','EO')]
              for edge in [
                {'source_id': w, 'source_type': 'Work', 'target_id': t, 'target_type': 'Task', 'relation': 'HAS_TASK'},
                {'source_id': t, 'source_type': 'Task', 'target_id': e, 'target_type': 'Event', 'relation': 'HAS_EVENT'}]]}


class SelectedWorkResponseTests(unittest.TestCase):
    def response(self, selection, grants=None):
        data = snapshot();store = Mock();store.snapshot.return_value = data
        api.app.dependency_overrides[api.demo_auth] = lambda: True
        api.app.dependency_overrides[api.slack_actor] = lambda: None if grants is None else {'person_id': 'WON'}
        try:
            with patch.object(api, '_frontend_store', return_value=store), \
                 patch.object(api, 'SupabaseStore', return_value=store), \
                 patch.object(api, '_overlay_original_work', return_value=(data, set(), {'events': []})), \
                 patch.object(api, '_all_messages', return_value=[{'message_id': 'S'+x, 'text': x} for x in ['A','B','O']]), \
                 patch.object(api, '_handover_db', return_value=[{'work_id': x} for x in grants or []]), \
                 patch.object(api, 'export_graph', side_effect=lambda s: {'metadata': {'num_nodes': len(s['works'])}}):
                return TestClient(api.app).get('/api/demo/data', params={'work_ids': selection})
        finally:
            api.app.dependency_overrides.clear()

    def test_one_selected_work_returns_one_graph(self):
        data = self.response('WORK-B').json()
        self.assertEqual([w['work_id'] for w in data['works']], ['WORK-B'])
        self.assertEqual([t['task_id'] for t in data['tasks']], ['TB'])
        self.assertEqual([m['message_id'] for m in data['slack_messages']], ['SB'])

    def test_n_selected_works_exclude_unselected_source_work(self):
        data = self.response('WORK-A,WORK-B').json()
        self.assertEqual(len(data['works']), 2)
        self.assertNotIn('WORK-OTHER', [w['work_id'] for w in data['works']])
        self.assertEqual(len(data['tasks']), 2)

    def test_query_never_expands_verified_grants(self):
        data = self.response('WORK-A,WORK-B', grants=['WORK-A']).json()
        self.assertEqual([w['work_id'] for w in data['works']], ['WORK-A'])

    def test_invalid_ids_rejected(self):
        self.assertEqual(self.response('WORK-A),WORK-B').status_code, 422)
