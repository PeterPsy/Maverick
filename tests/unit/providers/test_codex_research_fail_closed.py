from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from core.providers import codex_app_server_runtime_protocol as runtime_protocol
from core.providers.errors import ProviderLaunchError
from core.providers.provider_codex import CodexProviderAdapter
from core.providers.provider_codex_research import codex_research_runtime_version


ALLOWED_RESEARCH_ITEM_TYPES = (
    "agentMessage",
    "contextCompaction",
    "plan",
    "reasoning",
    "userMessage",
    "webSearch",
)
DENIED_RESEARCH_ITEM_TYPES = (
    "collabAgentToolCall",
    "commandExecution",
    "dynamicToolCall",
    "enteredReviewMode",
    "exitedReviewMode",
    "fileChange",
    "functionCallOutput",
    "hookPrompt",
    "imageGeneration",
    "imageView",
    "mcpToolCall",
    "sleep",
    "subAgentActivity",
    "unknownFutureItem",
)


class CodexResearchFailClosedTest(unittest.TestCase):
    def test_only_reviewed_passive_and_web_items_are_allowed(self) -> None:
        for item_type in ALLOWED_RESEARCH_ITEM_TYPES:
            with self.subTest(item_type=item_type), patch.object(
                runtime_protocol,
                "_put_completion",
            ) as complete, patch.object(runtime_protocol, "_emit"):
                runtime = _research_runtime()
                runtime_protocol._handle_item_event(
                    runtime,
                    provider_type="item.started",
                    item={"id": "item-1", "type": item_type, "query": "test"},
                )

                complete.assert_not_called()
                runtime.process.terminate.assert_not_called()

        for item_type in DENIED_RESEARCH_ITEM_TYPES:
            with self.subTest(item_type=item_type), patch.object(
                runtime_protocol,
                "_put_completion",
            ) as complete, patch.object(runtime_protocol, "_emit") as emit:
                runtime = _research_runtime()
                runtime_protocol._handle_item_event(
                    runtime,
                    provider_type="item.started",
                    item={"id": "item-1", "type": item_type},
                )

                self.assertEqual(
                    runtime.current_failure_reason_code,
                    "research_runtime_unavailable",
                )
                complete.assert_called_once_with(runtime, {"status": "failed"})
                runtime.process.terminate.assert_called_once()
                emit.assert_not_called()

    def test_launch_rechecks_a_replaced_codex_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            command = root / "codex"
            _write_codex_version(command, "0.153.4")
            adapter = CodexProviderAdapter(codex_command=str(command))
            self.assertTrue(adapter.research_runtime_available())

            _write_codex_version(command, "9.9.9")
            self.assertIsNone(codex_research_runtime_version(str(command)))
            session = SimpleNamespace(
                runtime_profile="research",
                runtime_root=str(root / "runtime"),
                workspace_root=str(root / "workspace"),
                effective_mode="full-access",
                device_use_binding=None,
            )
            with self.assertRaises(ProviderLaunchError) as raised:
                adapter.build_launch_spec(session)

            self.assertEqual(
                raised.exception.reason_code,
                "research_runtime_unavailable",
            )


def _research_runtime() -> SimpleNamespace:
    return SimpleNamespace(
        research=True,
        process=SimpleNamespace(terminate=unittest.mock.Mock()),
        event_lock=unittest.mock.MagicMock(),
        current_error_text=None,
        current_failure_reason_code=None,
        current_terminal_error_at=None,
    )


def _write_codex_version(command: Path, version: str) -> None:
    command.write_text(
        f"#!/bin/sh\nprintf 'codex-cli {version}\\n'\n",
        encoding="utf-8",
    )
    command.chmod(0o755)


if __name__ == "__main__":
    unittest.main()
