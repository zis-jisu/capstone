import asyncio
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock, patch
from fastapi import HTTPException
from src.sync_errors import sync_error_detail
from src.demo_frontend import _call_slack_mcp


class DiagnosticTests(unittest.TestCase):
    def test_anyio_group_preserves_slack_scope_error(self):
        error = ExceptionGroup('task group failed', [ExceptionGroup('inner', [
            HTTPException(502, 'Slack API error: missing_scope')])])
        detail = sync_error_detail(error, 'collect')
        self.assertIn('missing_scope', detail)
        self.assertIn('users:read', detail)
        self.assertNotIn('ExceptionGroup', detail)

    def test_secrets_and_bodies_never_returned(self):
        for error in [RuntimeError('vendor body xoxp-secret test-key private message'),
                      RuntimeError('OpenAI API error 401: {"message":"test-key private message invalid_api_key"}')]:
            detail = sync_error_detail(error, 'extract')
            self.assertNotIn('test-key', detail)
            self.assertNotIn('private message', detail)
            self.assertNotIn('xoxp-secret', detail)

    def test_db_failure_identifies_table(self):
        self.assertIn('slack_messages GET', sync_error_detail(RuntimeError('Supabase slack_messages GET failed: HTTP 400'), 'extract'))

    def test_ml_error_does_not_claim_slack_failed(self):
        self.assertIn('ML API 오류 (HTTP 403)', sync_error_detail(HTTPException(502, 'ML API returned HTTP 403'), 'training'))


class McpErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_error_escapes_as_http_not_task_group(self):
        @asynccontextmanager
        async def stdio(_params):
            yield (None, None)
        session = AsyncMock()
        session.__aenter__.return_value = session
        session.call_tool.return_value = Mock(isError=True, content=[Mock(type='text', text='Slack API error: missing_scope')])
        with patch.dict('os.environ', {'SLACK_TOKEN': 'fake-test'}), \
             patch('mcp.client.stdio.stdio_client', stdio), patch('mcp.ClientSession', return_value=session):
            with self.assertRaises(HTTPException) as error:
                await _call_slack_mcp('collect_slack_work_threads', {})
        self.assertIn('missing_scope', str(error.exception.detail))
