"""Tests for provider output normalization into runtime events."""

from __future__ import annotations

import json
import unittest

from core.runtime.execution import RuntimeOutputDeltaCoalescer, _record_process_line
from core.runtime.execution_events import RuntimeExecutionEvent, parse_provider_json_event


class RuntimeExecutionEventsTestCase(unittest.TestCase):
    def test_parse_plain_line_as_output_delta(self) -> None:
        event = parse_provider_json_event("thinking")

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "runtime.output.delta")
        self.assertEqual(event.payload["text"], "thinking")

    def test_parse_command_started_as_tool_call(self) -> None:
        event = parse_provider_json_event('{"type":"item.started","item":{"type":"command_execution","command":"ls"}}')

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "runtime.tool_call.started")
        self.assertEqual(event.payload["name"], "ls")

    def test_parse_codex_command_execution_started_as_first_class_tool_call(self) -> None:
        event = parse_provider_json_event('{"type":"item.started","item":{"id":"cmd_1","type":"commandExecution","command":"git status --short"}}')

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "runtime.tool_call.started")
        self.assertEqual(event.payload["name"], "command")
        self.assertEqual(event.payload["tool_kind"], "command")
        self.assertEqual(event.payload["tool_call_id"], "cmd_1")
        self.assertEqual(event.payload["command"], "git status --short")
        self.assertEqual(event.payload["summary"], "git status --short")

    def test_parse_command_completed_as_tool_call(self) -> None:
        event = parse_provider_json_event(
            '{"type":"item.completed","item":{"type":"command_execution","command":["git","status"],"exit_code":0,"aggregated_output":"clean"}}'
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "runtime.tool_call.completed")
        self.assertEqual(event.payload["name"], "git status")
        self.assertEqual(event.payload["exit_code"], 0)
        self.assertEqual(event.payload["output"], "clean")

    def test_parse_codex_command_execution_completed_as_first_class_tool_call(self) -> None:
        event = parse_provider_json_event(
            '{"type":"item.completed","item":{"id":"cmd_1","type":"commandExecution","command":"git status --short","exitCode":0,"aggregatedOutput":"clean"}}'
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "runtime.tool_call.completed")
        self.assertEqual(event.payload["name"], "command")
        self.assertEqual(event.payload["tool_kind"], "command")
        self.assertEqual(event.payload["tool_call_id"], "cmd_1")
        self.assertEqual(event.payload["command"], "git status --short")
        self.assertEqual(event.payload["exit_code"], 0)
        self.assertEqual(event.payload["output"], "clean")
        self.assertEqual(event.payload["summary"], "git status --short")

    def test_parse_codex_file_change_started_as_first_class_tool_call(self) -> None:
        event = parse_provider_json_event('{"type":"item.started","item":{"id":"fc_1","type":"fileChange"}}')

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "runtime.tool_call.started")
        self.assertEqual(event.payload["name"], "file_change")
        self.assertEqual(event.payload["tool_kind"], "file_change")
        self.assertEqual(event.payload["tool_call_id"], "fc_1")
        self.assertEqual(event.payload["summary"], "Applying file changes")

    def test_parse_codex_file_change_completed_as_first_class_tool_call(self) -> None:
        event = parse_provider_json_event(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "fc_1",
                        "type": "fileChange",
                        "changes": [
                            {"path": "apps/chat/main.tsx", "kind": {"type": "create"}, "diff": "+hello"},
                            {"path": "old.ts", "kind": {"type": "move", "move_path": "new.ts"}},
                        ],
                    },
                }
            )
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "runtime.tool_call.completed")
        self.assertEqual(event.payload["name"], "file_change")
        self.assertEqual(event.payload["tool_kind"], "file_change")
        self.assertEqual(event.payload["summary"], "Applied file changes")
        self.assertEqual(
            event.payload["changes"],
            [
                {"path": "apps/chat/main.tsx", "changeType": "add", "diff": "+hello", "movePath": None},
                {"path": "old.ts", "changeType": "move", "diff": None, "movePath": "new.ts"},
            ],
        )

    def test_parse_provider_event_without_text_as_step_update(self) -> None:
        event = parse_provider_json_event('{"type":"turn.started"}')

        self.assertIsNone(event)

    def test_parse_noisy_provider_lifecycle_events_as_internal_noise(self) -> None:
        self.assertIsNone(parse_provider_json_event('{"type":"thread.status.changed"}'))
        self.assertIsNone(parse_provider_json_event('{"type":"account.rateLimits.updated"}'))
        self.assertIsNone(parse_provider_json_event('{"type":"thread.tokenUsage.updated"}'))

    def test_parse_unknown_search_provider_event_as_tool_call(self) -> None:
        event = parse_provider_json_event('{"type":"web_search.started","item":{"query":"eventi domani pisa"}}')

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "runtime.tool_call.started")
        self.assertEqual(event.payload["provider_event_type"], "web_search.started")
        self.assertEqual(event.payload["raw"]["item"]["query"], "eventi domani pisa")

    def test_parse_codex_web_search_started_as_first_class_tool_call(self) -> None:
        event = parse_provider_json_event('{"type":"item.started","item":{"id":"ws_1","type":"webSearch","query":"eventi domani pisa"}}')

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "runtime.tool_call.started")
        self.assertEqual(event.payload["name"], "web_search")
        self.assertEqual(event.payload["tool_kind"], "web_search")
        self.assertEqual(event.payload["tool_call_id"], "ws_1")
        self.assertEqual(event.payload["summary"], "Searching the web")
        self.assertEqual(event.payload["query"], "eventi domani pisa")

    def test_parse_codex_web_search_completed_with_results_as_first_class_tool_call(self) -> None:
        event = parse_provider_json_event(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "ws_1",
                        "type": "webSearch",
                        "action": {"query": "eventi domani pisa"},
                        "results": [
                            {"title": "Eventi Pisa", "url": "https://example.test/pisa", "snippet": "Mostre e concerti"},
                            {"title": "Senza URL", "snippet": "Conferenza"},
                        ],
                    },
                }
            )
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "runtime.tool_call.completed")
        self.assertEqual(event.payload["name"], "web_search")
        self.assertEqual(event.payload["tool_kind"], "web_search")
        self.assertEqual(event.payload["tool_call_id"], "ws_1")
        self.assertEqual(event.payload["summary"], "eventi domani pisa")
        self.assertEqual(event.payload["query"], "eventi domani pisa")
        self.assertEqual(
            event.payload["results"],
            [
                {"title": "Eventi Pisa", "url": "https://example.test/pisa", "snippet": "Mostre e concerti"},
                {"title": "Senza URL", "url": None, "snippet": "Conferenza"},
            ],
        )

    def test_parse_tool_like_notification_without_lifecycle_as_completed(self) -> None:
        event = parse_provider_json_event('{"type":"codex_apps.progress_activity","name":"codex_apps","message":"loading tools"}')

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "runtime.tool_call.completed")
        self.assertEqual(event.payload["name"], "codex_apps")
        self.assertEqual(event.payload["summary"], "loading tools")

    def test_parse_stdin_prompt_as_internal_noise(self) -> None:
        self.assertIsNone(parse_provider_json_event("Reading additional input from stdin..."))
        self.assertIsNone(parse_provider_json_event('{"type":"provider.event","message":"Reading additional input from stdin..."}'))
        self.assertIsNone(parse_provider_json_event('{"type":"turn.completed"}'))

    def test_parse_turn_diff_update_as_internal_noise(self) -> None:
        self.assertIsNone(parse_provider_json_event("turn diff updated"))
        self.assertIsNone(parse_provider_json_event('{"type":"provider.event","message":"turn diff updated"}'))

    def test_stderr_json_provider_event_is_normalized(self) -> None:
        emitted: list[RuntimeExecutionEvent] = []

        _record_process_line(
            line='{"type":"item.started","item":{"type":"command_execution","command":"rg --files"}}',
            is_stderr=True,
            stdout_lines=[],
            stderr_lines=[],
            event_sink=emitted.append,
        )

        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0].event_type, "runtime.tool_call.started")
        self.assertEqual(emitted[0].payload["command"], "rg --files")

    def test_stdin_prompt_is_not_emitted_from_process_stream(self) -> None:
        emitted: list[RuntimeExecutionEvent] = []
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        _record_process_line(
            line="Reading additional input from stdin...",
            is_stderr=False,
            stdout_lines=stdout_lines,
            stderr_lines=stderr_lines,
            event_sink=emitted.append,
        )
        _record_process_line(
            line="Reading additional input from stdin...",
            is_stderr=True,
            stdout_lines=stdout_lines,
            stderr_lines=stderr_lines,
            event_sink=emitted.append,
        )

        self.assertEqual(emitted, [])
        self.assertEqual(stdout_lines, [])
        self.assertEqual(stderr_lines, [])

    def test_output_delta_coalescer_batches_adjacent_small_deltas(self) -> None:
        emitted: list[RuntimeExecutionEvent] = []
        coalescer = RuntimeOutputDeltaCoalescer(emitted.append, flush_chars=100)

        coalescer.emit(RuntimeExecutionEvent(event_type="runtime.output.delta", payload={"text": "hel"}))
        coalescer.emit(RuntimeExecutionEvent(event_type="runtime.output.delta", payload={"text": "lo"}))
        self.assertEqual(emitted, [])

        coalescer.emit(RuntimeExecutionEvent(event_type="runtime.tool_call.started", payload={"name": "rg"}))

        self.assertEqual([event.event_type for event in emitted], ["runtime.output.delta", "runtime.tool_call.started"])
        self.assertEqual(emitted[0].payload["text"], "hello")


if __name__ == "__main__":
    unittest.main()
