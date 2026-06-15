"""Tests for provider-history tool-output compaction hooks."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from core.providers.provider_codex_hooks import _codex_post_tool_use_hook_source
from core.runtime.output_compaction.models import ToolOutputCompactionPolicy
from core.runtime.output_compaction.provider_hooks import (
    PROVIDER_HISTORY_TOOL_RESULT_SCOPE,
    build_codex_post_tool_use_response,
)


class ProviderHookCompactionTest(unittest.TestCase):
    def test_codex_post_tool_use_replaces_large_bash_output_before_provider_history(self) -> None:
        huge_stdout = "Authorization: Bearer secret-token\n" + (
            "FAILED tests/test_example.py::test_case\n"
            "Traceback (most recent call last):\n"
            "AssertionError: expected 1 got 2\n"
        ) * 800

        response = build_codex_post_tool_use_response(
            {
                "hook_event_name": "PostToolUse",
                "tool_name": "Bash",
                "tool_use_id": "tool-1",
                "tool_input": {"command": "python -m pytest tests/test_example.py"},
                "tool_response": {"stdout": huge_stdout, "stderr": "", "exit_code": 1},
            },
            runtime_session_id="sess-1",
            policy=ToolOutputCompactionPolicy(
                min_original_bytes=1000,
                failure_min_savings_ratio=0.20,
                failure_target_max_compacted_bytes=4000,
            ),
        )

        self.assertTrue(response["emit"])
        hook_response = response["response"]
        self.assertEqual(hook_response["decision"], "block")
        self.assertFalse(hook_response["continue"])
        self.assertIn("[tool output compacted]", hook_response["reason"])
        self.assertIn(f"scope: {PROVIDER_HISTORY_TOOL_RESULT_SCOPE}", hook_response["reason"])
        self.assertNotIn("secret-token", hook_response["reason"])
        metadata = response["output_compaction"]
        self.assertEqual(metadata["scope"], PROVIDER_HISTORY_TOOL_RESULT_SCOPE)
        self.assertEqual(metadata["provider_hook"], "codex.PostToolUse")
        self.assertEqual(metadata["tool_name"], "Bash")
        self.assertTrue(metadata["applied"])
        self.assertIn("stdout", metadata["fields"])

    def test_codex_post_tool_use_leaves_short_unredacted_output_unchanged(self) -> None:
        response = build_codex_post_tool_use_response(
            {
                "hook_event_name": "PostToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "printf ok"},
                "tool_response": {"stdout": "ok\n", "exit_code": 0},
            },
            runtime_session_id="sess-1",
            policy=ToolOutputCompactionPolicy(min_original_bytes=1000),
        )

        self.assertFalse(response["emit"])

    def test_codex_post_tool_use_redacts_short_payload_without_dropping_fields(self) -> None:
        response = build_codex_post_tool_use_response(
            {
                "hook_event_name": "PostToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "curl https://example.invalid"},
                "tool_response": {
                    "output": "request summary",
                    "stdout": "Authorization: Bearer secret-token\nok\n",
                    "stderr": "API_TOKEN=secret-value\n",
                    "exit_code": 0,
                },
            },
            runtime_session_id="sess-1",
            policy=ToolOutputCompactionPolicy(min_original_bytes=1000),
        )

        self.assertTrue(response["emit"])
        reason = response["response"]["reason"]
        self.assertIn("request summary", reason)
        self.assertIn("stdout:\nAuthorization: Bearer <redacted>", reason)
        self.assertIn("stderr:\nAPI_TOKEN=<redacted>", reason)
        self.assertNotIn("secret-token", reason)
        self.assertNotIn("secret-value", reason)
        self.assertEqual(response["output_compaction"]["pass_through_reason"], "below_min_original_bytes")

    def test_codex_post_tool_use_accepts_alias_payload_shapes(self) -> None:
        huge_output = "FAILED test_alias\nTraceback\n" + ("diagnostic line\n" * 2000)

        response = build_codex_post_tool_use_response(
            {
                "hookEventName": "PostToolUse",
                "toolName": "Bash",
                "toolUseId": "tool-alias",
                "toolInput": "pytest tests/test_alias.py",
                "toolResult": {"content": [{"type": "text", "text": huge_output}], "exitCode": 1},
            },
            runtime_session_id="sess-1",
            policy=ToolOutputCompactionPolicy(
                min_original_bytes=1000,
                failure_min_savings_ratio=0.20,
                failure_target_max_compacted_bytes=4000,
            ),
        )

        self.assertTrue(response["emit"])
        self.assertIn("[tool output compacted]", response["response"]["reason"])
        self.assertIn("test_alias", response["response"]["reason"])
        self.assertEqual(response["output_compaction"]["provider_hook"], "codex.PostToolUse")

    def test_codex_post_tool_use_fails_open_with_redacted_text_when_compactor_raises(self) -> None:
        huge_stdout = "Authorization: Bearer secret-token\n" + ("large output line\n" * 2000)

        with patch(
            "core.runtime.output_compaction.provider_hooks.compact_tool_output",
            side_effect=RuntimeError("boom"),
        ):
            response = build_codex_post_tool_use_response(
                {
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "pytest"},
                    "tool_response": {"stdout": huge_stdout, "exit_code": 1},
                },
                runtime_session_id="sess-1",
                policy=ToolOutputCompactionPolicy(min_original_bytes=1000),
            )

        self.assertTrue(response["emit"])
        self.assertEqual(response["response"]["decision"], "block")
        self.assertIn("Authorization: Bearer <redacted>", response["response"]["reason"])
        self.assertNotIn("secret-token", response["response"]["reason"])
        self.assertLessEqual(
            len(response["response"]["reason"].encode("utf-8")),
            response["output_compaction"]["target_max_compacted_bytes"],
        )
        self.assertEqual(response["output_compaction"]["pass_through_reason"], "compactor_failed")
        self.assertEqual(response["output_compaction"]["compaction_error"], "RuntimeError")

    def test_runtime_local_hook_script_fallback_redacts_and_bounds_output(self) -> None:
        namespace: dict[str, object] = {"__name__": "hook_test"}
        exec(_codex_post_tool_use_hook_source(), namespace)
        fallback_response = namespace["fallback_response"]
        huge_stdout = "API_TOKEN=secret-value\n" + ("diagnostic line\n" * 2000)

        response = fallback_response(  # type: ignore[operator]
            {
                "hook_event_name": "PostToolUse",
                "tool_name": "Bash",
                "tool_response": {"stdout": huge_stdout, "exit_code": 1},
            }
        )

        self.assertIsNotNone(response)
        assert isinstance(response, dict)
        self.assertEqual(response["decision"], "block")
        self.assertFalse(response["continue"])
        self.assertIn("scope: provider_history_tool_result", response["reason"])
        self.assertIn("pass_through_reason: hook_bridge_unavailable", response["reason"])
        self.assertNotIn("secret-value", response["reason"])
        self.assertLessEqual(len(response["reason"].encode("utf-8")), 13_500)

        with patch.dict(namespace["os"].environ, {"MAVERICK_RUNTIME_OUTPUT_COMPACTION": "0"}):  # type: ignore[index, union-attr]
            disabled_response = fallback_response(  # type: ignore[operator]
                {
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "tool_response": {"stdout": huge_stdout, "exit_code": 1},
                }
            )
        self.assertIsNone(disabled_response)

    def test_runtime_local_hook_script_fallback_accepts_response_aliases(self) -> None:
        namespace: dict[str, object] = {"__name__": "hook_test"}
        exec(_codex_post_tool_use_hook_source(), namespace)
        fallback_response = namespace["fallback_response"]
        huge_output = "Cookie: session=secret\n" + ("diagnostic line\n" * 2000)

        response = fallback_response(  # type: ignore[operator]
            {
                "hookEventName": "PostToolUse",
                "toolName": "Bash",
                "toolResult": {"content": [{"type": "text", "text": huge_output}], "exitCode": 1},
            }
        )

        self.assertIsNotNone(response)
        assert isinstance(response, dict)
        self.assertEqual(response["decision"], "block")
        self.assertIn("scope: provider_history_tool_result", response["reason"])
        self.assertNotIn("session=secret", response["reason"])

    def test_runtime_local_hook_script_fallback_redacts_core_sensitive_patterns(self) -> None:
        namespace: dict[str, object] = {"__name__": "hook_test"}
        exec(_codex_post_tool_use_hook_source(), namespace)
        fallback_response = namespace["fallback_response"]
        huge_output = "\n".join(
            [
                "DATABASE_URL=https://user:pass@example.test/db",
                "GET https://example.test/path?Access_Token=SecretToken&ok=1",
                "openai sk-secretOpenAIStyleKey1234567890",
                "github ghp_secretGithubToken1234567890",
                "-----BEGIN PRIVATE KEY-----",
                "private-key-material",
                "-----END PRIVATE KEY-----",
                *("diagnostic line" for _index in range(2000)),
            ]
        )

        response = fallback_response(  # type: ignore[operator]
            {
                "hook_event_name": "PostToolUse",
                "tool_name": "Bash",
                "tool_response": {"stdout": huge_output, "exit_code": 1},
            }
        )

        self.assertIsNotNone(response)
        assert isinstance(response, dict)
        reason = response["reason"]
        self.assertNotIn("user:pass", reason)
        self.assertNotIn("SecretToken", reason)
        self.assertNotIn("secretOpenAIStyleKey", reason)
        self.assertNotIn("secretGithubToken", reason)
        self.assertNotIn("private-key-material", reason)
        self.assertIn("<redacted", reason)


if __name__ == "__main__":
    unittest.main()
