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

    def test_redacts_sensitive_keyed_non_string_values_in_provider_compact_profile(self) -> None:
        cases = (
            (
                "numeric scalar",
                {"api_key": 1234567890, "name": "kept"},
                "api_key",
                "data.api_key",
                ("1234567890",),
            ),
            (
                "nested object",
                {"token": {"id": 987654321, "value": "nested-secret"}, "name": "kept"},
                "token",
                "data.token",
                ("987654321", "nested-secret"),
            ),
            (
                "nested list",
                {"token": [246813579, "list-secret"], "name": "kept"},
                "token",
                "data.token",
                ("246813579", "list-secret"),
            ),
        )

        for name, data, sensitive_key, field_path, raw_fragments in cases:
            with self.subTest(name=name):
                compacted = compact_runtime_cli_result(
                    {"status_code": 200, "data": data},
                    argv=["app", "example", "mcp", "call", "keyed"],
                    runtime_session_id="sess-1",
                    policy=ToolOutputCompactionPolicy(min_original_bytes=1000),
                )

                self.assertEqual(compacted["data"][sensitive_key], "<redacted>")
                self.assertEqual(compacted["data"]["name"], "kept")
                for raw_fragment in raw_fragments:
                    self.assertNotIn(raw_fragment, str(compacted))
                metadata = compacted["output_compaction"]
                self.assertFalse(metadata["applied"])
                self.assertTrue(metadata["redacted"])
                self.assertEqual(metadata["pass_through_reason"], "sensitive_key_redacted")
                self.assertEqual(metadata["fields"], [field_path])

    def test_provider_compact_preserves_developer_context_document_body(self) -> None:
        document = "# Architecture\n\n" + ("document paragraph with exact context\n" * 5000)
        compacted = compact_runtime_cli_result(
            {
                "status_code": 200,
                "doc_id": "core_architecture",
                "title": "Core Architecture",
                "source_path": "docs/architecture/core_architecture.md",
                "content": document,
            },
            argv=["core", "cli", "run", "developer-context.read", "--doc-id", "core_architecture", "--json"],
            runtime_session_id="sess-1",
            policy=ToolOutputCompactionPolicy(min_original_bytes=1000),
        )

        self.assertEqual(compacted["content"], document)
        self.assertNotIn("output_compaction", compacted)

    def test_provider_compact_preserves_storage_text_document_body(self) -> None:
        document = "# Storage Guide\n\n" + ("storage document line\n" * 5000)
        compacted = compact_runtime_cli_result(
            {
                "status_code": 200,
                "file": {
                    "role": "generated",
                    "workspace_relative_path": "storage/generated/guides/storage-guide.md",
                },
                "text": document,
                "text_char_count": len(document),
                "offset": 0,
                "range_end": len(document),
                "has_more": False,
                "next_offset": None,
                "complete": True,
            },
            argv=[
                "app",
                "storage",
                "mcp",
                "call",
                "storage_read_text",
                "--json",
                "--workspace_relative_path",
                "storage/generated/guides/storage-guide.md",
            ],
            runtime_session_id="sess-1",
            policy=ToolOutputCompactionPolicy(min_original_bytes=1000),
        )

        self.assertEqual(compacted["text"], document)
        self.assertNotIn("output_compaction", compacted)

    def test_provider_compact_preserves_storage_preview_text_for_handoffs(self) -> None:
        preview = "Memory-ready preview\n" + ("preview line\n" * 3000)
        compacted = compact_runtime_cli_result(
            {
                "status_code": 200,
                "file": {
                    "role": "generated",
                    "workspace_relative_path": "storage/generated/brief.md",
                },
                "preview_text": preview,
                "preview_truncated": True,
            },
            argv=["app", "storage", "mcp", "call", "storage_preview_text", "--json"],
            runtime_session_id="sess-1",
            policy=ToolOutputCompactionPolicy(min_original_bytes=1000),
        )

        self.assertEqual(compacted["preview_text"], preview)
        self.assertNotIn("output_compaction", compacted)

    def test_provider_compact_redacts_preserved_document_bodies_without_truncating(self) -> None:
        cases = (
            (
                "developer context",
                "content",
                {
                    "status_code": 200,
                    "doc_id": "core_architecture",
                    "title": "Core Architecture",
                    "source_path": "docs/architecture/core_architecture.md",
                    "content": "Intro\nAPI_TOKEN=doc-secret-value\n" + ("developer paragraph\n" * 5000) + "FINAL-MARKER",
                },
                ["core", "cli", "run", "developer-context.read", "--doc-id", "core_architecture", "--json"],
            ),
            (
                "storage text",
                "text",
                {
                    "status_code": 200,
                    "file": {
                        "role": "generated",
                        "workspace_relative_path": "storage/generated/guides/storage-guide.md",
                    },
                    "text": "Intro\nAPI_TOKEN=storage-secret-value\n" + ("storage paragraph\n" * 5000) + "FINAL-MARKER",
                    "text_char_count": 95_000,
                    "offset": 0,
                    "range_end": 95_000,
                    "has_more": False,
                    "next_offset": None,
                    "complete": True,
                },
                ["app", "storage", "mcp", "call", "storage_read_text", "--json"],
            ),
            (
                "storage preview",
                "preview_text",
                {
                    "status_code": 200,
                    "file": {
                        "role": "generated",
                        "workspace_relative_path": "storage/generated/brief.md",
                    },
                    "preview_text": "Intro\nAPI_TOKEN=preview-secret-value\n" + ("preview paragraph\n" * 3000) + "FINAL-MARKER",
                    "preview_truncated": True,
                },
                ["app", "storage", "mcp", "call", "storage_preview_text", "--json"],
            ),
        )

        for name, field_name, result, argv in cases:
            with self.subTest(name=name):
                compacted = compact_runtime_cli_result(
                    result,
                    argv=argv,
                    runtime_session_id="sess-1",
                    policy=ToolOutputCompactionPolicy(min_original_bytes=1000),
                )

                self.assertIn("API_TOKEN=<redacted>", compacted[field_name])
                self.assertIn("FINAL-MARKER", compacted[field_name])
                self.assertNotIn("[tool output compacted]", compacted[field_name])
                self.assertNotIn("secret-value", compacted[field_name])
                self.assertEqual(compacted["output_compaction"]["fields"], [field_name])
                self.assertEqual(compacted["output_compaction"]["pass_through_reason"], "document_body_redacted")

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
