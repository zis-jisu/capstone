import io
import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from src.demo_frontend import slack_permalink


class SlackPermalinkTests(unittest.TestCase):
    def test_uses_slack_permalink_for_authorized_event(self):
        data = {'events': [{'event_id': 'EVENT-1', 'source_id': 'C123ABC:1791608400.000001', 'conversation_type': 'channel'}]}
        response = io.BytesIO(json.dumps({
            'ok': True, 'permalink': 'https://example.slack.com/archives/C123ABC/p1791608400000001'
        }).encode())
        with patch('src.demo_frontend.SupabaseStore') as store, \
             patch('src.demo_frontend._filter_work_data', return_value=(data, [])) as filter_work, \
             patch('src.demo_frontend.urllib.request.urlopen', return_value=response) as urlopen, \
             patch.dict('os.environ', {'SLACK_TOKEN': 'test-token'}):
            store.return_value.request.return_value = [{'message_id': 'C123ABC:1791608400.000001'}]
            result = slack_permalink('EVENT-1', actor=None)
        self.assertEqual(result.status_code, 302)
        self.assertEqual(filter_work.call_args.args[2], {'WORK-00020'})
        self.assertEqual(result.headers['location'], 'https://example.slack.com/archives/C123ABC/p1791608400000001')
        self.assertIn('message_ts=1791608400.000001', urlopen.call_args.args[0].full_url)

    def test_event_outside_authorized_data_is_rejected(self):
        with patch('src.demo_frontend.SupabaseStore'), \
             patch('src.demo_frontend._filter_work_data', return_value=({'events': []}, [])):
            with self.assertRaises(HTTPException) as error:
                slack_permalink('EVENT-1', actor=None)
        self.assertEqual(error.exception.status_code, 404)


if __name__ == '__main__':
    unittest.main()
