from __future__ import annotations

import unittest
from unittest.mock import patch

from core.runtime.output_compaction.cli_result import compact_runtime_cli_result, runtime_cli_output_profile
from core.runtime.output_compaction.models import ToolOutputCompactionPolicy


class RuntimeCliResultCompactionTest(unittest.TestCase):
    def test_output_profile_parser_defaults_and_rejects_unknown_values(self) -> None:
        self.assertEqual(runtime_cli_output_profile({}), ("full", None))
        self.assertEqual(runtime_cli_output_profile({"output_profile": "provider_compact"}), ("provider_compact", None))
        self.assertEqual(runtime_cli_output_profile({"output_profile": "unknown"}), (None, "invalid_output_profile"))
        self.assertEqual(runtime_cli_output_profile({"output_profile": 123}), (None, "invalid_output_profile"))

    def test_compacts_nested_large_text_without_overwriting_result_metadata(self) -> None:
        huge_output = "Authorization: Bearer secret-token\n" + ("nested output line\n" * 10_000)
        result = {
            "status_code": 200,
            "data": [{"content": huge_output}],
            "output_compaction": {"owner": "app-result"},
        }

        compacted = compact_runtime_cli_result(
            result,
            argv=["app", "example", "mcp", "call", "large"],
            runtime_session_id="sess-1",
            policy=ToolOutputCompactionPolicy(min_original_bytes=1000, success_min_savings_ratio=0.50),
        )

        self.assertEqual(result["data"][0]["content"], huge_output)
        self.assertEqual(compacted["output_compaction"], {"owner": "app-result"})
        self.assertIn("[tool output compacted]", compacted["data"][0]["content"])
        self.assertNotIn("secret-token", compacted["data"][0]["content"])
        self.assertEqual(compacted["runtime_cli_output_compaction"]["scope"], "runtime_cli_response")
        self.assertEqual(compacted["runtime_cli_output_compaction"]["fields"], ["data[0].content"])

    def test_redacts_short_sensitive_text_in_provider_compact_profile(self) -> None:
        compacted = compact_runtime_cli_result(
            {"status_code": 200, "content": "Authorization: Bearer short-secret\nok"},
            argv=["app", "example", "mcp", "call", "short"],
            runtime_session_id="sess-1",
            policy=ToolOutputCompactionPolicy(min_original_bytes=1000),
        )

        self.assertEqual(compacted["content"], "Authorization: Bearer <redacted>\nok")
        self.assertNotIn("short-secret", str(compacted))
        metadata = compacted["output_compaction"]
        self.assertFalse(metadata["applied"])
        self.assertTrue(metadata["redacted"])
        self.assertEqual(metadata["pass_through_reason"], "below_min_original_bytes")
        self.assertEqual(metadata["fields"], ["content"])

    def test_redacts_sensitive_keyed_text_in_provider_compact_profile(self) -> None:
        compacted = compact_runtime_cli_result(
            {"status_code": 200, "data": {"api_key": "short-secret", "name": "kept"}},
            argv=["app", "example", "mcp", "call", "keyed"],
            runtime_session_id="sess-1",
            policy=ToolOutputCompactionPolicy(min_original_bytes=1000),
        )

        self.assertEqual(compacted["data"]["api_key"], "<redacted>")
        self.assertEqual(compacted["data"]["name"], "kept")
        self.assertNotIn("short-secret", str(compacted))
        metadata = compacted["output_compaction"]
        self.assertFalse(metadata["applied"])
        self.assertTrue(metadata["redacted"])
        self.assertEqual(metadata["pass_through_reason"], "sensitive_key_redacted")
        self.assertEqual(metadata["fields"], ["data.api_key"])

    def test_compactor_error_returns_redacted_field_instead_of_raw_output(self) -> None:
        huge_output = "Authorization: Bearer secret-token\n" + ("large output line\n" * 10_000)

        with patch(
            "core.runtime.output_compaction.cli_result.compact_tool_output",
            side_effect=RuntimeError("boom"),
        ):
            compacted = compact_runtime_cli_result(
                {"status_code": 200, "content": huge_output},
                argv=["core", "cli", "run", "large"],
                runtime_session_id="sess-1",
                policy=ToolOutputCompactionPolicy(min_original_bytes=1000),
            )

        self.assertNotEqual(compacted["content"], huge_output)
        self.assertIn("Authorization: Bearer <redacted>", compacted["content"])
        self.assertNotIn("secret-token", compacted["content"])
        self.assertEqual(compacted["output_compaction"]["pass_through_reason"], "compactor_failed")
        self.assertEqual(compacted["output_compaction"]["compaction_error"], "RuntimeError")


if __name__ == "__main__":
    unittest.main()
