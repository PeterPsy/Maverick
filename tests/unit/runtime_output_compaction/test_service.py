from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
import unittest

from core.runtime.execution_events import RuntimeExecutionEvent
from core.runtime.output_compaction import ToolOutputCompactionContext
from core.runtime.output_compaction.models import ToolOutputCompactionInput, ToolOutputCompactionPolicy
from core.runtime.output_compaction.rules import CompactionRule
from core.runtime.output_compaction.classifier import classify_tool_output
from core.runtime.output_compaction.service import compact_tool_call_event


FIXTURES_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "runtime_output_compaction"


def fixture_text(name: str) -> str:
    return (FIXTURES_ROOT / name).read_text(encoding="utf-8")


class RuntimeOutputCompactionServiceTest(unittest.TestCase):
    def test_short_output_passes_through_after_redaction_with_metadata(self) -> None:
        event = RuntimeExecutionEvent(
            event_type="runtime.tool_call.completed",
            payload={
                "name": "command",
                "status": "completed",
                "command": "curl https://example.test?token=secret",
                "output": "Authorization: Bearer secret-token\nok",
            },
        )

        compacted = compact_tool_call_event(
            event,
            policy=ToolOutputCompactionPolicy(min_original_bytes=1000),
        )

        payload = compacted.payload
        self.assertEqual(payload["output"], "Authorization: Bearer <redacted>\nok")
        self.assertEqual(payload["command"], "curl https://example.test?token=<redacted>")
        self.assertFalse(payload["output_compaction"]["applied"])
        self.assertEqual(payload["output_compaction"]["pass_through_reason"], "below_min_original_bytes")
        self.assertNotIn("secret-token", str(payload))
        self.assertNotIn("secret", payload["command"])
        self.assertEqual(payload["output_compaction"]["digest_kind"], "redacted_sha256")

    def test_command_and_summary_are_redacted_when_output_is_bounded_pass_through(self) -> None:
        secret_command = "curl 'https://example.test?token=secret-query' -H 'Authorization: Bearer secret-header'"
        output = "line\n" * 12_000
        event = RuntimeExecutionEvent(
            event_type="runtime.tool_call.completed",
            payload={
                "name": "command",
                "status": "completed",
                "command": secret_command,
                "summary": secret_command,
                "exit_code": 0,
                "output": output,
            },
        )

        compacted = compact_tool_call_event(
            event,
            policy=ToolOutputCompactionPolicy(
                min_original_bytes=1000,
                success_min_savings_ratio=0.999,
                target_max_compacted_bytes=4000,
            ),
        )

        payload = compacted.payload
        metadata = payload["output_compaction"]
        self.assertFalse(metadata["applied"])
        self.assertEqual(metadata["pass_through_reason"], "insufficient_savings_success")
        self.assertTrue(metadata["bounded_pass_through"])
        self.assertLessEqual(len(payload["output"].encode("utf-8")), metadata["target_max_compacted_bytes"])
        self.assertIn("[tool output bounded]", payload["output"])
        self.assertIn("command", metadata["fields"])
        self.assertIn("summary", metadata["fields"])
        self.assertNotIn("secret-query", str(payload))
        self.assertNotIn("secret-header", str(payload))
        self.assertEqual(
            payload["command"],
            "curl 'https://example.test?token=<redacted>' -H 'Authorization: Bearer <redacted>'",
        )
        self.assertEqual(payload["summary"], payload["command"])

    def test_pytest_failure_long_output_compacts_and_preserves_diagnostics(self) -> None:
        diagnostic = "\n".join(
            [
                "FAILED tests/test_widget.py::test_renders_total - AssertionError: expected 2",
                "Traceback (most recent call last):",
                "  File \"tests/test_widget.py\", line 42, in test_renders_total",
                "AssertionError: expected 2",
                "short test summary info",
                "FAILED tests/test_widget.py::test_renders_total",
                "1 failed, 7 passed in 3.21s",
            ]
        )
        output = ("setup noise\n" * 5000) + diagnostic + ("\nteardown noise" * 5000)
        raw = {"type": "item.completed", "item": {"type": "commandExecution", "aggregatedOutput": output}}
        event = RuntimeExecutionEvent(
            event_type="runtime.tool_call.failed",
            payload={
                "name": "command",
                "tool_kind": "command",
                "status": "failed",
                "command": "python -m pytest tests/test_widget.py",
                "exit_code": 1,
                "output": output,
                "raw": raw,
            },
        )

        compacted = compact_tool_call_event(
            event,
            context=ToolOutputCompactionContext(session_id="sess-1", turn_id="turn-1"),
            policy=ToolOutputCompactionPolicy(min_original_bytes=1000, failure_target_max_compacted_bytes=12_000),
        )

        payload = compacted.payload
        self.assertTrue(payload["output_compaction"]["applied"])
        self.assertEqual(payload["output_compaction"]["rule_id"], "tests/pytest_unittest")
        self.assertEqual(payload["output_compaction"]["required_savings_ratio"], 0.70)
        self.assertIn("[tool output compacted]", payload["output"])
        self.assertIn("FAILED tests/test_widget.py::test_renders_total", payload["output"])
        self.assertIn("AssertionError", payload["output"])
        self.assertLess(payload["output_compaction"]["compacted_bytes"], payload["output_compaction"]["original_bytes"])
        self.assertNotIn("aggregatedOutput", payload["raw"]["item"])
        self.assertTrue(payload["raw"]["has_omitted_provider_payload"])
        self.assertIn("raw.item.aggregatedOutput", payload["output_compaction"]["fields"])

    def test_successful_output_requires_success_savings_ratio(self) -> None:
        output = "\n".join(f"line {index}: build cache entry" for index in range(5000))
        event = RuntimeExecutionEvent(
            event_type="runtime.tool_call.completed",
            payload={
                "name": "command",
                "status": "completed",
                "command": "npm run build",
                "exit_code": 0,
                "output": output,
            },
        )

        compacted = compact_tool_call_event(
            event,
            policy=ToolOutputCompactionPolicy(
                min_original_bytes=1000,
                success_min_savings_ratio=0.999,
                target_max_compacted_bytes=12_000,
            ),
        )

        metadata = compacted.payload["output_compaction"]
        self.assertFalse(metadata["applied"])
        self.assertEqual(metadata["pass_through_reason"], "insufficient_savings_success")
        self.assertTrue(metadata["bounded_pass_through"])
        self.assertLessEqual(len(compacted.payload["output"].encode("utf-8")), metadata["target_max_compacted_bytes"])
        self.assertIn("[tool output bounded]", compacted.payload["output"])
        self.assertEqual(metadata["required_savings_ratio"], 0.999)

    def test_node_test_runner_failure_uses_node_rule_and_preserves_file_line(self) -> None:
        diagnostic = "\n".join(
            [
                " FAIL  src/widget.test.ts > renders total",
                "Error: expected 2 to equal 3",
                "  at src/widget.test.ts:17:12",
                "Test Files  1 failed | 4 passed",
            ]
        )
        output = ("vite noise\n" * 5000) + diagnostic + ("\nmore node noise" * 5000)
        event = RuntimeExecutionEvent(
            event_type="runtime.tool_call.failed",
            payload={"name": "command", "status": "failed", "command": "pnpm test", "exit_code": 1, "output": output},
        )

        compacted = compact_tool_call_event(event, policy=ToolOutputCompactionPolicy(min_original_bytes=1000))

        payload = compacted.payload
        self.assertTrue(payload["output_compaction"]["applied"])
        self.assertEqual(payload["output_compaction"]["rule_id"], "tests/node_runner")
        self.assertIn("src/widget.test.ts:17:12", payload["output"])
        self.assertIn("Test Files", payload["output"])

    def test_git_status_large_output_preserves_branch_counts_and_samples(self) -> None:
        output = "\n".join(
            [
                "On branch feature/output-compaction",
                "Your branch is ahead of 'origin/design' by 2 commits.",
                "Changes not staged for commit:",
                *[f"\tmodified:   file_{index}.py" for index in range(1200)],
                "Untracked files:",
                *[f"\tnew_{index}.txt" for index in range(400)],
            ]
        )
        event = RuntimeExecutionEvent(
            event_type="runtime.tool_call.completed",
            payload={"name": "command", "status": "completed", "command": "git status --short", "exit_code": 0, "output": output},
        )

        compacted = compact_tool_call_event(event, policy=ToolOutputCompactionPolicy(min_original_bytes=1000, target_max_compacted_bytes=4000))

        payload = compacted.payload
        self.assertTrue(payload["output_compaction"]["applied"])
        self.assertEqual(payload["output_compaction"]["rule_id"], "vcs/git_status")
        self.assertIn("On branch feature/output-compaction", payload["output"])
        self.assertIn("modified: 1200", payload["output"])
        self.assertIn("untracked: 400", payload["output"])

    def test_git_status_short_porcelain_fixture_uses_git_status_rule(self) -> None:
        output = "\n".join(fixture_text("git_status_large.txt").strip().splitlines() * 800)
        event = RuntimeExecutionEvent(
            event_type="runtime.tool_call.completed",
            payload={
                "name": "command",
                "status": "completed",
                "command": "git status --short --branch",
                "exit_code": 0,
                "output": output,
            },
        )

        compacted = compact_tool_call_event(
            event,
            policy=ToolOutputCompactionPolicy(
                min_original_bytes=1000,
                success_min_savings_ratio=0.5,
                target_max_compacted_bytes=4000,
            ),
        )

        payload = compacted.payload
        facts = payload["output_compaction"]["facts"]
        self.assertTrue(payload["output_compaction"]["applied"])
        self.assertEqual(payload["output_compaction"]["rule_id"], "vcs/git_status")
        self.assertIn("## feature/output-compaction...origin/design [ahead 2]", payload["output"])
        self.assertEqual(facts["modified_count"], 1600)
        self.assertEqual(facts["added_count"], 800)
        self.assertEqual(facts["deleted_count"], 800)
        self.assertEqual(facts["renamed_count"], 800)
        self.assertEqual(facts["untracked_count"], 800)
        self.assertEqual(facts["conflicted_count"], 800)

    def test_failed_git_status_without_status_signal_uses_generic_fallback(self) -> None:
        output = "fatal: not a git repository (or any of the parent directories): .git\n" + ("noise line\n" * 8000)
        event = RuntimeExecutionEvent(
            event_type="runtime.tool_call.failed",
            payload={
                "name": "command",
                "status": "failed",
                "command": "git status --short",
                "exit_code": 128,
                "output": output,
            },
        )

        compacted = compact_tool_call_event(
            event,
            policy=ToolOutputCompactionPolicy(
                min_original_bytes=1000,
                failure_target_max_compacted_bytes=4000,
            ),
        )

        payload = compacted.payload
        self.assertTrue(payload["output_compaction"]["applied"])
        self.assertEqual(payload["output_compaction"]["rule_id"], "generic/fallback")
        self.assertIn("fatal: not a git repository", payload["output"])
        self.assertNotIn("git status summary", payload["output"])

    def test_large_json_output_uses_json_rule(self) -> None:
        output = json.dumps(
            {
                "status": "ok",
                "message": "indexed",
                "items": [{"id": index, "name": f"item-{index}", "detail": "x" * 20} for index in range(1000)],
            }
        )
        event = RuntimeExecutionEvent(
            event_type="runtime.tool_call.completed",
            payload={"name": "command", "status": "completed", "command": "curl https://api.example.test/items", "exit_code": 0, "output": output},
        )

        compacted = compact_tool_call_event(event, policy=ToolOutputCompactionPolicy(min_original_bytes=1000, target_max_compacted_bytes=4000))

        payload = compacted.payload
        self.assertTrue(payload["output_compaction"]["applied"])
        self.assertEqual(payload["output_compaction"]["rule_id"], "data/json_large")
        self.assertIn("json root: object", payload["output"])
        self.assertIn("top_level_keys: status, message, items", payload["output"])
        self.assertIn("items: array length 1000", payload["output"])

    def test_ansi_sequences_are_stripped_from_compacted_output(self) -> None:
        output = ("normal\n" * 5000) + "\x1b[31mERROR failed loudly\x1b[0m\n" + ("tail\n" * 5000)
        event = RuntimeExecutionEvent(
            event_type="runtime.tool_call.failed",
            payload={"name": "command", "status": "failed", "command": "custom-check", "exit_code": 1, "output": output},
        )

        compacted = compact_tool_call_event(event, policy=ToolOutputCompactionPolicy(min_original_bytes=1000))

        self.assertTrue(compacted.payload["output_compaction"]["applied"])
        self.assertIn("ERROR failed loudly", compacted.payload["output"])
        self.assertNotIn("\x1b[31m", compacted.payload["output"])

    def test_invalid_rule_regex_is_ignored_and_fallback_still_matches(self) -> None:
        selection = classify_tool_output(
            ToolOutputCompactionInput(
                provider_id=None,
                provider_event_type=None,
                runtime_session_id=None,
                turn_id=None,
                event_type="runtime.tool_call.completed",
                tool_call_id=None,
                tool_name="command",
                tool_kind="command",
                command="custom",
                argv=("custom",),
                cwd=None,
                output="plain",
                stdout=None,
                stderr=None,
                exit_code=0,
                raw=None,
                metadata={"status": "completed"},
            ),
            "plain",
            rules=(
                CompactionRule(rule_id="bad/rule", family="bad", priority=10, reducer="generic", text_regex_any=("[",)),
                CompactionRule(rule_id="generic/fallback", family="generic", priority=0, reducer="generic_fallback"),
            ),
        )

        self.assertEqual(selection.rule_id, "generic/fallback")

    def test_redaction_failure_omits_large_payload_instead_of_persisting_raw_text(self) -> None:
        output = "secret output\n" * 5000
        event = RuntimeExecutionEvent(
            event_type="runtime.tool_call.failed",
            payload={
                "name": "command",
                "status": "failed",
                "command": "pytest",
                "exit_code": 1,
                "output": output,
                "raw": {"item": {"type": "commandExecution", "aggregatedOutput": output}},
            },
        )

        with patch("core.runtime.output_compaction.service.redact_text", side_effect=RuntimeError("boom")):
            compacted = compact_tool_call_event(
                event,
                policy=ToolOutputCompactionPolicy(min_original_bytes=1000),
            )

        payload = compacted.payload
        self.assertEqual(payload["output"], "[tool output omitted: redaction_failed]")
        self.assertEqual(payload["output_compaction"]["pass_through_reason"], "redaction_failed")
        self.assertTrue(payload["output_compaction"]["redaction_failed"])
        self.assertNotIn("secret output", str(payload["raw"]))
        self.assertNotIn("secret output", payload["output"])

    def test_digest_is_computed_on_redacted_text(self) -> None:
        base_payload = {
            "name": "command",
            "status": "completed",
            "command": "env",
        }
        first = compact_tool_call_event(
            RuntimeExecutionEvent(
                event_type="runtime.tool_call.completed",
                payload={**base_payload, "output": "API_TOKEN=first-secret"},
            ),
            policy=ToolOutputCompactionPolicy(min_original_bytes=1000),
        )
        second = compact_tool_call_event(
            RuntimeExecutionEvent(
                event_type="runtime.tool_call.completed",
                payload={**base_payload, "output": "API_TOKEN=second-secret"},
            ),
            policy=ToolOutputCompactionPolicy(min_original_bytes=1000),
        )

        self.assertEqual(first.payload["output"], "API_TOKEN=<redacted>")
        self.assertEqual(second.payload["output"], "API_TOKEN=<redacted>")
        self.assertEqual(first.payload["output_compaction"]["digest"], second.payload["output_compaction"]["digest"])

    def test_feature_flag_disables_compaction(self) -> None:
        event = RuntimeExecutionEvent(
            event_type="runtime.tool_call.completed",
            payload={"name": "command", "output": "Authorization: Bearer secret"},
        )

        with patch.dict("os.environ", {"MAVERICK_RUNTIME_OUTPUT_COMPACTION": "0"}):
            compacted = compact_tool_call_event(event)

        self.assertIs(compacted, event)
        self.assertNotIn("output_compaction", compacted.payload)

    def test_unexpected_compactor_error_records_redacted_fallback(self) -> None:
        output = "Authorization: Bearer secret-token\n" + ("long output\n" * 2000)
        event = RuntimeExecutionEvent(
            event_type="runtime.tool_call.completed",
            payload={
                "name": "command",
                "output": output,
                "raw": {"item": {"type": "commandExecution", "aggregatedOutput": output}},
            },
        )

        with patch("core.runtime.output_compaction.service.compact_tool_output", side_effect=RuntimeError("boom")):
            compacted = compact_tool_call_event(event, policy=ToolOutputCompactionPolicy(min_original_bytes=1000))

        self.assertIsNot(compacted, event)
        payload = compacted.payload
        self.assertEqual(payload["output_compaction"]["pass_through_reason"], "compactor_failed")
        self.assertEqual(payload["output_compaction"]["compaction_error"], "RuntimeError")
        self.assertIn("compactor_failed", payload["output"])
        self.assertLessEqual(len(payload["output"].encode("utf-8")), payload["output_compaction"]["target_max_compacted_bytes"])
        self.assertIn("Authorization: Bearer <redacted>", payload["output"])
        self.assertNotIn("secret-token", str(payload))
        self.assertNotIn("aggregatedOutput", payload["raw"]["item"])

    def test_short_chat_render_json_remains_available_for_existing_consumers(self) -> None:
        output = '{"status_code": 200, "chat_render": {"kind": "checklist.design", "payload": {"id": "check_1"}}}'
        event = RuntimeExecutionEvent(
            event_type="runtime.tool_call.completed",
            payload={"name": "command", "status": "completed", "command": "maverick app checklist", "output": output},
        )

        compacted = compact_tool_call_event(event, policy=ToolOutputCompactionPolicy(min_original_bytes=1000))

        self.assertEqual(compacted.payload["output"], output)
        self.assertFalse(compacted.payload["output_compaction"]["applied"])

    def test_raw_only_redaction_is_reflected_in_metadata(self) -> None:
        event = RuntimeExecutionEvent(
            event_type="runtime.tool_call.completed",
            payload={
                "name": "command",
                "raw": {"item": {"type": "commandExecution", "metadata": {"api_key": "secret-key"}}},
            },
        )

        compacted = compact_tool_call_event(event)

        payload = compacted.payload
        self.assertEqual(payload["raw"]["item"]["metadata"]["api_key"], "<redacted>")
        self.assertEqual(payload["output_compaction"]["pass_through_reason"], "no_text_fields")
        self.assertTrue(payload["output_compaction"]["redacted"])

    def test_compacted_header_byte_count_matches_metadata(self) -> None:
        output = (
            "FAILED tests/test_widget.py::test_renders_total - AssertionError\n"
            "Traceback (most recent call last):\n"
            "AssertionError: expected 2\n"
            "short test summary info\n"
        ) + ("noise\n" * 20_000)
        event = RuntimeExecutionEvent(
            event_type="runtime.tool_call.failed",
            payload={"name": "command", "status": "failed", "command": "pytest", "exit_code": 1, "output": output},
        )

        compacted = compact_tool_call_event(
            event,
            policy=ToolOutputCompactionPolicy(min_original_bytes=1000, failure_target_max_compacted_bytes=4000),
        )

        payload = compacted.payload
        metadata = payload["output_compaction"]
        header = payload["output"].split("\n\n", 1)[0]
        header_values = {
            key: value
            for line in header.splitlines()
            if ": " in line
            for key, value in [line.split(": ", 1)]
        }
        self.assertEqual(int(header_values["compacted_bytes"]), metadata["compacted_bytes"])
        self.assertEqual(float(header_values["savings_ratio"]), metadata["savings_ratio"])


if __name__ == "__main__":
    unittest.main()
