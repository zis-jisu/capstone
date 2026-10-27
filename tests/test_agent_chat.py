import base64
import importlib.util
import os
import unittest
from unittest.mock import patch

FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None
if FASTAPI_AVAILABLE:
    from fastapi import HTTPException
    from src.agent_chat import ChatRequest, _authorize, ask_agent
    from src.luna_api import MODEL


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed in this Python environment")
class AgentChatTest(unittest.TestCase):
    def setUp(self):
        self.request = ChatRequest(
            question="가장 먼저 할 일은?",
            task_id="TASK-1",
            tasks=[{
                "task_id": "TASK-1",
                "name": "계약서 검토",
                "status": "진행 중",
                "deadline": "오늘 17:00",
                "priority_score": 91.5,
                "next_action": "법무팀 의견 확인",
            }],
        )

    def test_uses_shared_luna_client_and_returns_task_sources(self):
        env = {"API_ACCESS_TOKEN": "test-token", "OPENAI_API_KEY": "server-key"}
        with patch.dict(os.environ, env, clear=True), patch(
            "src.agent_chat.call_text", return_value=("법무팀 의견을 확인하세요.", {})
        ) as call:
            result = ask_agent(self.request, "Bearer test-token")

        self.assertEqual(MODEL, "gpt-6-luna")
        self.assertEqual(result["model"], MODEL)
        self.assertEqual(result["sources"], [{"type": "frontend_task", "task_id": "TASK-1"}])
        payload = call.call_args.kwargs["user_payload"]
        self.assertEqual(payload["context"]["selected_task"]["priority_score"], 91.5)

    def test_accepts_existing_demo_basic_auth(self):
        token = base64.b64encode("demo-user:demo-pass".encode()).decode()
        env = {"DEMO_USERNAME": "demo-user", "DEMO_PASSWORD": "demo-pass"}
        with patch.dict(os.environ, env, clear=True):
            self.assertIsNone(_authorize("Basic " + token))

    def test_rejects_unauthorized_request(self):
        with patch.dict(os.environ, {"API_ACCESS_TOKEN": "expected"}, clear=True):
            with self.assertRaises(HTTPException) as raised:
                _authorize("Bearer wrong")
        self.assertEqual(raised.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
