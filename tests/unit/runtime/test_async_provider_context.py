"""Governed provider-context coverage for asynchronous runtime turns."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import patch

from core.providers.provider_credentials import bind_provider_credential
from core.providers.models import ProviderSelection
from core.providers.service import builtin_provider_registry, register_builtin_providers
from core.providers.store import ProviderCollections, ProviderDocumentStore
from core.runtime.event_bus import RuntimeEventBus
from core.runtime.execution import execute_runtime_turn
from core.runtime.plain_hosted_text import execute_plain_hosted_text_turn
from core.runtime.service import create_runtime_session
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.thread_event_bus import RuntimeThreadEventBus
from core.runtime.turn_submission import submit_runtime_turn_async
from core.secrets.service import build_secret_ref, create_platform_secret
from core.secrets.store import SecretCollections, SecretDocumentStore
from tests.support.collections import FakeCollection


class AsyncProviderContextTest(unittest.TestCase):
    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repository_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repository_root / name).mkdir(parents=True, exist_ok=True)
        (repository_root / "AGENTS.md").write_text("", encoding="utf-8")
        self.state = _state(repository_root)

    def test_plain_hosted_async_dispatch_receives_context_without_persisting_it(self) -> None:
        session = create_runtime_session(
            self.state.runtime_store,
            session_id="plain-context",
            workspace_id="default",
            agent_id="chat",
            runtime_mode="plain_hosted_chat",
            start_path=self.state.repository_root,
        )
        original_input = "Come sta andando?"
        provider_input = f"{original_input}\n\n[Maverick governed orchestration read]\nRun is active."

        with (
            patch.dict("os.environ", {"MAVERICK_HOSTED_TEXT_FAKE_RESPONSE": "Procede bene."}, clear=False),
            patch("core.runtime.turn_submission_service_output.schedule_runtime_thread_title_generation"),
            patch(
                "core.runtime.turn_submission_service_runtime.generalist_orchestration_input_text",
                return_value=provider_input,
            ) as attach_context,
            patch(
                "core.runtime.turn_submission_service_runtime.execute_plain_hosted_text_turn",
                wraps=execute_plain_hosted_text_turn,
            ) as execute_hosted,
        ):
            turn, _events = submit_runtime_turn_async(self.state, session=session, input_text=original_input)
            current = self._wait_for_terminal_turn(turn.turn_id)

        self.assertEqual(current.status, "completed")
        attach_context.assert_called_once()
        self.assertIs(attach_context.call_args.args[0], self.state)
        self.assertEqual(attach_context.call_args.kwargs["session"].session_id, session.session_id)
        self.assertEqual(attach_context.call_args.kwargs["input_text"], original_input)
        self.assertEqual(execute_hosted.call_args.kwargs["input_text"], provider_input)
        self.assertEqual(self.state.runtime_store.get_turn(turn.turn_id).input_text, original_input)
        self.assertNotIn(provider_input, str(self.state.runtime_store.list_events(session.session_id)))

    def test_agentic_async_dispatch_receives_context_without_persisting_it(self) -> None:
        session = create_runtime_session(
            self.state.runtime_store,
            session_id="agentic-context",
            workspace_id="default",
            agent_id="chat",
            start_path=self.state.repository_root,
        )
        original_input = "Aggiornami sulla board."
        provider_input = f"{original_input}\n\n[Maverick governed orchestration read]\nRun is active."

        with (
            patch.dict("os.environ", {"MAVERICK_RUNTIME_FAKE_RESPONSE": "Board aggiornata."}, clear=False),
            patch("core.runtime.turn_submission_service_output.schedule_runtime_thread_title_generation"),
            patch("core.runtime.turn_submission_service_runtime._wait_for_session_prewarm"),
            patch("core.runtime.turn_submission_service_runtime._build_launch_spec_for_execution", return_value=None),
            patch("core.runtime.turn_submission_service_runtime.release_idle_runtime_processes"),
            patch("core.runtime.turn_submission_service_runtime.schedule_runtime_session_prewarm"),
            patch(
                "core.runtime.turn_submission_service_runtime.runtime_provider_input_text",
                return_value=provider_input,
            ) as build_provider_input,
            patch(
                "core.runtime.turn_submission_service_runtime.execute_runtime_turn",
                wraps=execute_runtime_turn,
            ) as execute_agentic,
        ):
            turn, _events = submit_runtime_turn_async(self.state, session=session, input_text=original_input)
            current = self._wait_for_terminal_turn(turn.turn_id)

        self.assertEqual(current.status, "completed", current.failure_reason)
        build_provider_input.assert_called_once()
        self.assertIs(build_provider_input.call_args.args[0], self.state)
        self.assertEqual(build_provider_input.call_args.kwargs["session"].session_id, session.session_id)
        self.assertEqual(build_provider_input.call_args.kwargs["input_text"], original_input)
        self.assertEqual(build_provider_input.call_args.kwargs["app_references"], [])
        self.assertIsNone(build_provider_input.call_args.kwargs["attachments"])
        self.assertEqual(execute_agentic.call_args.kwargs["input_text"], provider_input)
        self.assertEqual(self.state.runtime_store.get_turn(turn.turn_id).input_text, original_input)
        self.assertNotIn(provider_input, str(self.state.runtime_store.list_events(session.session_id)))

    def _wait_for_terminal_turn(self, turn_id: str):
        for _ in range(200):
            current = self.state.runtime_store.get_turn(turn_id)
            if current.status in {"completed", "failed", "cancelled", "timed-out"}:
                return current
            time.sleep(0.01)
        self.fail(f"Runtime turn {turn_id} did not reach a terminal state.")


def _state(repository_root: Path) -> SimpleNamespace:
    provider_store = ProviderDocumentStore(
        ProviderCollections(
            definitions=FakeCollection(),
            bindings=FakeCollection(),
            selections=FakeCollection(),
        )
    )
    register_builtin_providers(provider_store)
    codex = builtin_provider_registry().get_provider_definition("codex")
    provider_store.save_provider_definition(replace(codex, status="active"))
    now = datetime.now(tz=UTC)
    provider_store.save_provider_selection(
        ProviderSelection(
            selection_id="selection-default-codex",
            workspace_id="default",
            provider_id="codex",
            binding_id=None,
            selection_scope="workspace",
            selection_reason="async provider context test",
            created_at=now,
            updated_at=now,
        )
    )
    openrouter = builtin_provider_registry().get_provider_definition("openrouter")
    provider_store.save_provider_definition(replace(openrouter, status="active"))
    secret_store = SecretDocumentStore(
        SecretCollections(
            secrets=FakeCollection(),
            values=FakeCollection(),
            bindings=FakeCollection(),
            grants=FakeCollection(),
        ),
        key_loader=lambda: b"test-key-material-async-provider-context",
    )
    secret = create_platform_secret(
        secret_store,
        label="OpenRouter",
        raw_value="test-openrouter-key",
        alias="openrouter-runtime-key",
        kind="api_key",
    )
    bind_provider_credential(
        provider_store,
        provider_id="openrouter",
        workspace_id="default",
        secret_ref=build_secret_ref(alias=secret.alias),
    )
    runtime_store = RuntimeDocumentStore(
        RuntimeCollections(
            sessions=FakeCollection(),
            turns=FakeCollection(),
            events=FakeCollection(),
            processes=FakeCollection(),
            states=FakeCollection(),
            threads=FakeCollection(),
        )
    )
    return SimpleNamespace(
        provider_store=provider_store,
        secret_store=secret_store,
        runtime_store=runtime_store,
        runtime_event_bus=RuntimeEventBus(),
        runtime_thread_event_bus=RuntimeThreadEventBus(),
        repository_root=repository_root,
        observability_store=None,
    )


if __name__ == "__main__":
    unittest.main()
