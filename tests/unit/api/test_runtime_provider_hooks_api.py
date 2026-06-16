"""Tests for runtime-token provider hook bridge APIs."""

from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.runtime_provider_hooks_api import CODEX_POST_TOOL_USE_HOOK_PATH, handle_runtime_provider_hooks_api


class RuntimeProviderHooksApiTest(unittest.TestCase):
    def test_codex_post_tool_use_hook_returns_compacted_provider_history_payload(self) -> None:
        state = self._state()
        huge_stdout = "Authorization: Bearer secret-token\n" + ("FAILED test_case\nTraceback\n" * 2000)

        with self._trusted_runtime():
            status, payload = self._invoke_hook_api(
                state,
                {
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "tool_use_id": "tool-1",
                    "tool_input": {"command": "pytest tests"},
                    "tool_response": {"stdout": huge_stdout, "exit_code": 1},
                },
            )

        self.assertEqual(status, "200 OK")
        self.assertTrue(payload["emit"])
        self.assertEqual(payload["response"]["decision"], "block")
        self.assertFalse(payload["response"]["continue"])
        self.assertIn("[tool output compacted]", payload["response"]["reason"])
        self.assertIn("scope: provider_history_tool_result", payload["response"]["reason"])
        self.assertNotIn("secret-token", payload["response"]["reason"])
        self.assertEqual(payload["output_compaction"]["scope"], "provider_history_tool_result")
        self.assertEqual(payload["output_compaction"]["provider_hook"], "codex.PostToolUse")

    def test_codex_post_tool_use_hook_rejects_inactive_runtime_session(self) -> None:
        state = self._state(status="stopped")

        with self._trusted_runtime():
            status, payload = self._invoke_hook_api(
                state,
                {
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "tool_response": {"stdout": "ok\n", "exit_code": 0},
                },
            )

        self.assertEqual(status, "401 Unauthorized")
        self.assertEqual(payload["error"], "runtime_session_not_active")

    def test_codex_post_tool_use_hook_rejects_invalid_runtime_session_record(self) -> None:
        def raise_invalid_session(_session_id: str):
            raise ValueError("Unsupported runtime thread visibility `not-hidden`.")

        state = self._state(get_session=raise_invalid_session)

        with self._trusted_runtime():
            status, payload = self._invoke_hook_api(
                state,
                {
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "tool_response": {"stdout": "ok\n", "exit_code": 0},
                },
            )

        self.assertEqual(status, "401 Unauthorized")
        self.assertEqual(payload["error"], "runtime_session_not_found")

    def test_unknown_runtime_provider_hook_route_is_not_handled(self) -> None:
        response = handle_runtime_provider_hooks_api(
            self._state(),
            {"PATH_INFO": "/api/runtime/provider-hooks/other", "REQUEST_METHOD": "POST"},
            lambda _status, _headers: None,
        )

        self.assertIsNone(response)

    def _state(self, *, status: str = "running", get_session=None) -> SimpleNamespace:
        if get_session is None:
            get_session = lambda _session_id: SimpleNamespace(
                effective_mode="sandbox",
                session_id="sess-1",
                status=status,
                workspace_id="default",
            )
        return SimpleNamespace(
            runtime_store=SimpleNamespace(
                get_session=get_session
            )
        )

    @contextmanager
    def _trusted_runtime(self):
        with patch(
            "core.api.runtime_provider_hooks_api._runtime_claims",
            return_value=({"runtime_session_id": "sess-1", "workspace_id": "default", "mode": "sandbox"}, None),
        ):
            yield

    def _invoke_hook_api(self, state: SimpleNamespace, payload: dict) -> tuple[str, dict]:
        body = json.dumps(payload).encode("utf-8")
        status_holder: list[str] = []

        response = handle_runtime_provider_hooks_api(
            state,
            {
                "CONTENT_LENGTH": str(len(body)),
                "PATH_INFO": CODEX_POST_TOOL_USE_HOOK_PATH,
                "REQUEST_METHOD": "POST",
                "wsgi.input": BytesIO(body),
            },
            lambda status, _headers: status_holder.append(status),
        )

        self.assertIsNotNone(response)
        assert response is not None
        return status_holder[0], json.loads(b"".join(response).decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
