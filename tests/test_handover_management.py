from base64 import b64encode
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from src import demo_frontend as demo


class HandoverManagementTests(unittest.TestCase):
    def setUp(self):
        credentials = b64encode(b'demo:demo-password').decode()
        self.client = TestClient(demo.app, headers={'Authorization': f'Basic {credentials}'})
        env = patch.dict(os.environ, {
            'DEMO_USERNAME': 'demo', 'DEMO_PASSWORD': 'demo-password',
            'ADMIN_PASSWORD': 'admin-password', 'ADMIN_ACTOR_ID': '',
            'SLACK_CLIENT_ID': '', 'SLACK_CLIENT_SECRET': '', 'SLACK_REDIRECT_URI': '',
        })
        env.start()
        self.addCleanup(env.stop)

    def test_bulk_approve_skips_handled_rows_and_ranks_each_receiver_once(self):
        ids = [str(uuid4()) for _ in range(3)]
        rows = [{'request_id': request_id, 'source_person_id': 'OWNER', 'requester_id': 'RECIPIENT'}
                for request_id in ids]
        with patch.object(demo, '_handover_db', side_effect=[rows, rows[:2]]) as storage, \
                patch.object(demo, '_approved_handoff_source_ids', return_value=['OWNER']), \
                patch.object(demo.ml_bridge, 'priorities') as rank:
            result = self.client.post('/api/demo/handover-requests/bulk-decision', json={
                'actor_id': 'OWNER', 'request_ids': ids + [ids[0].upper()],
            })
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {'approved': 2, 'count': 3, 'skipped': 1})
        update = storage.call_args_list[1]
        self.assertEqual(update.args, ('PATCH',))
        self.assertEqual(update.kwargs['params']['status'], 'eq.pending')
        self.assertEqual(update.kwargs['params']['source_person_id'], 'eq.OWNER')
        rank.assert_called_once_with(person_ids=['OWNER'], receiver_person_id='RECIPIENT')

    def test_bulk_approval_rejects_requests_owned_by_other_people(self):
        request_id = str(uuid4())
        with patch.object(demo, '_handover_db', return_value=[{'source_person_id': 'OTHER'}]) as storage:
            result = self.client.post('/api/demo/handover-requests/bulk-decision', json={
                'actor_id': 'OWNER', 'request_ids': [request_id],
            })
        self.assertEqual(result.status_code, 403)
        storage.assert_called_once()

    def test_admin_and_manager_can_assign_without_actor_configuration(self):
        snapshot = {
            'persons': [{'person_id': 'SOURCE'}, {'person_id': 'RECIPIENT'}],
            'works': [{'work_id': 'W1'}],
            'tasks': [{'task_id': 'T1', 'status': 'in_progress'}, {'task_id': 'T2', 'status': '완료'}],
            'edges': [
                {'source_type': 'Work', 'source_id': 'W1', 'target_type': 'Task',
                 'target_id': task_id, 'relation': 'HAS_TASK'} for task_id in ('T1', 'T2')
            ] + [{'source_type': 'Person', 'source_id': 'SOURCE', 'target_type': 'Task',
                  'target_id': 'T1', 'relation': 'OWNER'}],
        }
        body = {'work_id': 'W1', 'source_person_id': 'SOURCE', 'assignee_id': 'RECIPIENT'}
        endpoints = (
            ('admin', {'X-Admin-Token': 'admin-password'}, 'DEMO-ADMIN'),
            ('manager', {'X-Demo-Role': 'manager'}, demo.MARKETING_MANAGER_DEMO_ID),
        )
        with patch.object(demo, '_hybrid_frontend_snapshot', return_value=snapshot), \
                patch.object(demo.ml_bridge, 'priorities', return_value={'priorities': []}):
            for role, headers, actor in endpoints:
                with self.subTest(role=role):
                    path = f'/api/{role}/assignments'
                    self.assertEqual(self.client.post(path, json=body).status_code, 403)
                    row = {'task_id': 'T1', 'assignee_id': 'RECIPIENT', 'assigned_by': actor}
                    with patch.object(demo, '_db_assignments', side_effect=[[row], [], [row]]) as storage:
                        result = self.client.post(path, json=body, headers=headers)
                        retry = self.client.post(path, json=body, headers=headers)
                    self.assertEqual(result.status_code, 201)
                    self.assertEqual(result.json()['task_ids'], ['T1'])
                    self.assertEqual(retry.json(), result.json())
                    self.assertEqual(storage.call_args_list[0].kwargs['rows'], [row])
