"""Plain hosted chat runtime integration tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import patch

from core.providers.provider_credentials import bind_provider_credential
from core.providers.service import builtin_provider_registry, register_builtin_providers
from core.providers.store import ProviderCollections, ProviderDocumentStore
from core.runtime.event_bus import RuntimeEventBus
from core.runtime.plain_hosted_text import execute_plain_hosted_text_turn
from core.runtime.runtime_session import runtime_session_from_document
from core.runtime.service import create_runtime_session
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.thread_event_bus import RuntimeThreadEventBus
from core.runtime.turn_submission import submit_runtime_turn, submit_runtime_turn_async
from core.api.runtime_api import _session_payload, _submit_runtime_turn_response, _turn_payload
from core.secrets.service import build_secret_ref, create_platform_secret
from core.secrets.store import SecretCollections, SecretDocumentStore
from tests.support.collections import FakeCollection


class PlainHostedRuntimeTest(unittest.TestCase):
    def make_provider_store(self) -> ProviderDocumentStore:
        store = ProviderDocumentStore(
            ProviderCollections(
                definitions=FakeCollection(),
                bindings=FakeCollection(),
                selections=FakeCollection(),
            )
        )
        register_builtin_providers(store)
        openrouter = builtin_provider_registry().get_provider_definition("openrouter")
        store.save_provider_definition(replace(openrouter, status="active"))
        return store

    def make_secret_store(self) -> SecretDocumentStore:
        return SecretDocumentStore(
            SecretCollections(
                secrets=FakeCollection(),
                values=FakeCollection(),
                bindings=FakeCollection(),
                grants=FakeCollection(),
            ),
            key_loader=lambda: b"test-key-material-plain-hosted",
        )

    def make_runtime_store(self) -> RuntimeDocumentStore:
        return RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
            )
        )

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def make_state(self):
        provider_store = self.make_provider_store()
        secret_store = self.make_secret_store()
        secret = create_platform_secret(
            secret_store,
            label="OpenRouter",
            raw_value="super-secret-token",
            alias="openrouter-runtime-key",
            kind="api_key",
        )
        bind_provider_credential(
            provider_store,
            provider_id="openrouter",
            workspace_id="default",
            secret_ref=build_secret_ref(alias="openrouter-runtime-key"),
        )
        return SimpleNamespace(
            provider_store=provider_store,
            secret_store=secret_store,
            runtime_store=self.make_runtime_store(),
            runtime_event_bus=RuntimeEventBus(),
            runtime_thread_event_bus=RuntimeThreadEventBus(),
            repository_root=self.make_repo_root(),
            observability_store=None,
        )

    def test_legacy_session_hydrates_runtime_mode_agentic(self) -> None:
        now = datetime(2026, 6, 22, 12, 0, tzinfo=UTC)
        session = runtime_session_from_document(
            {
                "session_id": "sess-legacy",
                "workspace_id": "default",
                "agent_id": "chat",
                "status": "created",
                "requested_mode": None,
                "effective_mode": "sandbox",
                "workspace_root": "/workspace",
                "workdir": "/workspace",
                "runtime_root": "/workspace/runtime/sess-legacy",
                "started_at": None,
                "updated_at": now,
                "ended_at": None,
                "last_progress_at": None,
            }
        )

        self.assertEqual(session.runtime_mode, "agentic")

    def test_create_runtime_session_defaults_and_persists_runtime_mode(self) -> None:
        state = self.make_state()
        agentic = create_runtime_session(
            state.runtime_store,
            session_id="sess-agentic",
            workspace_id="default",
            agent_id="chat",
            start_path=state.repository_root,
        )
        plain = create_runtime_session(
            state.runtime_store,
            session_id="sess-plain",
            workspace_id="default",
            agent_id="chat",
            runtime_mode="plain_hosted_chat",
            start_path=state.repository_root,
        )

        self.assertEqual(agentic.runtime_mode, "agentic")
        self.assertEqual(plain.runtime_mode, "plain_hosted_chat")
        self.assertEqual(state.runtime_store.get_session("sess-plain").runtime_mode, "plain_hosted_chat")
        self.assertEqual(_session_payload(plain)["runtime_mode"], "plain_hosted_chat")

    def test_create_runtime_session_persists_hosted_model_override(self) -> None:
        state = self.make_state()
        plain = create_runtime_session(
            state.runtime_store,
            session_id="sess-openrouter",
            workspace_id="default",
            agent_id="chat",
            runtime_mode="plain_hosted_chat",
            hosted_provider_id="openrouter",
            hosted_model_id="google/gemma-4-31b-it:free",
            start_path=state.repository_root,
        )

        self.assertEqual(plain.hosted_provider_id, "openrouter")
        self.assertEqual(plain.hosted_model_id, "google/gemma-4-31b-it:free")
        self.assertEqual(_session_payload(plain)["hosted_model_id"], "google/gemma-4-31b-it:free")

    def test_plain_hosted_sync_turn_emits_delta_final_and_completes(self) -> None:
        state = self.make_state()
        session = create_runtime_session(
            state.runtime_store,
            session_id="sess-plain",
            workspace_id="default",
            agent_id="chat",
            runtime_mode="plain_hosted_chat",
            start_path=state.repository_root,
        )

        with (
            patch.dict("os.environ", {"MAVERICK_HOSTED_TEXT_FAKE_CHUNKS": "[\"hel\", \"lo\"]"}, clear=False),
            patch("core.runtime.turn_submission_service_output.schedule_runtime_thread_title_generation"),
            patch(
                "core.runtime.turn_submission_service_submit.resolve_runtime_backend_for_session",
                side_effect=AssertionError("agentic runtime should not be resolved"),
            ),
        ):
            turn, _events = submit_runtime_turn(state, session=session, input_text="Hello")

        event_types = [event.event_type for event in state.runtime_store.list_events(session.session_id)]
        final_events = [event for event in state.runtime_store.list_events(session.session_id) if event.event_type == "runtime.output.final"]
        self.assertEqual(turn.status, "completed")
        self.assertEqual(state.runtime_store.get_turn(turn.turn_id).runtime_mode, "plain_hosted_chat")
        self.assertEqual(_turn_payload(turn)["runtime_mode"], "plain_hosted_chat")
        self.assertEqual(state.runtime_store.get_session(session.session_id).provider_id, "openrouter")
        self.assertIn("runtime.output.delta", event_types)
        self.assertIn("runtime.output.final", event_types)
        self.assertIn("runtime.turn.completed", event_types)
        self.assertEqual(final_events[-1].payload["complete_text"], "hello")
        self.assertNotIn("super-secret-token", str(state.runtime_store.list_events(session.session_id)))
        self.assertNotIn("runtime.step.updated", event_types)

    def test_plain_hosted_provider_receives_governed_orchestration_context(self) -> None:
        state = self.make_state()
        session = create_runtime_session(
            state.runtime_store,
            session_id="sess-governed-context",
            workspace_id="default",
            agent_id="chat",
            runtime_mode="plain_hosted_chat",
            start_path=state.repository_root,
        )
        governed_input = "Come sta andando?\n\n[Maverick governed orchestration read]\nRun is active."

        with (
            patch.dict("os.environ", {"MAVERICK_HOSTED_TEXT_FAKE_RESPONSE": "status response"}, clear=False),
            patch("core.runtime.turn_submission_service_output.schedule_runtime_thread_title_generation"),
            patch(
                "core.runtime.turn_submission_service_sync_hosted.generalist_orchestration_input_text",
                return_value=governed_input,
            ) as attach_context,
            patch(
                "core.runtime.turn_submission_service_sync_hosted.execute_plain_hosted_text_turn",
                wraps=execute_plain_hosted_text_turn,
            ) as execute_hosted,
        ):
            turn, _events = submit_runtime_turn(state, session=session, input_text="Come sta andando?")

        self.assertEqual(turn.status, "completed")
        attach_context.assert_called_once()
        self.assertEqual(execute_hosted.call_args.kwargs["input_text"], governed_input)
        self.assertEqual(state.runtime_store.get_turn(turn.turn_id).input_text, "Come sta andando?")

    def test_plain_hosted_turn_with_image_uses_multimodal_openrouter_model(self) -> None:
        state = self.make_state()
        session = create_runtime_session(
            state.runtime_store,
            session_id="sess-openrouter-image",
            workspace_id="default",
            agent_id="chat",
            runtime_mode="plain_hosted_chat",
            hosted_provider_id="openrouter",
            hosted_model_id="google/gemma-4-31b-it:free",
            start_path=state.repository_root,
        )
        image_path = Path(session.workspace_root) / "storage" / "uploaded" / "image-1" / "pixel.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"png-bytes")

        with (
            patch.dict("os.environ", {"MAVERICK_HOSTED_TEXT_FAKE_RESPONSE": "image response"}, clear=False),
            patch("core.runtime.turn_submission_service_output.schedule_runtime_thread_title_generation"),
            patch(
                "core.runtime.turn_submission_service_submit.resolve_runtime_backend_for_session",
                side_effect=AssertionError("agentic runtime should not be resolved"),
            ),
        ):
            turn, _events = submit_runtime_turn(
                state,
                session=session,
                input_text="Describe it",
                attachments=[
                    {
                        "name": "pixel.png",
                        "type": "image/png",
                        "isImage": True,
                        "relativePath": "storage/uploaded/image-1/pixel.png",
                    }
                ],
            )

        self.assertEqual(turn.status, "completed")
        saved_session = state.runtime_store.get_session(session.session_id)
        self.assertEqual(saved_session.provider_id, "openrouter")
        self.assertEqual(saved_session.hosted_model_id, "google/gemma-4-31b-it:free")

    def test_plain_hosted_text_only_model_blocks_image_attachments(self) -> None:
        state = self.make_state()
        session = create_runtime_session(
            state.runtime_store,
            session_id="sess-openrouter-text-only",
            workspace_id="default",
            agent_id="chat",
            runtime_mode="plain_hosted_chat",
            hosted_provider_id="openrouter",
            hosted_model_id="nvidia/nemotron-3-ultra-550b-a55b:free",
            start_path=state.repository_root,
        )
        image_path = Path(session.workspace_root) / "storage" / "uploaded" / "image-1" / "pixel.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"png-bytes")

        with patch("core.runtime.turn_submission_service_output.schedule_runtime_thread_title_generation"):
            turn, _events = submit_runtime_turn(
                state,
                session=session,
                input_text="Describe it",
                attachments=[
                    {
                        "name": "pixel.png",
                        "type": "image/png",
                        "isImage": True,
                        "relativePath": "storage/uploaded/image-1/pixel.png",
                    }
                ],
            )

        self.assertEqual(turn.status, "failed")
        self.assertEqual(
            turn.failure_reason,
            "The selected model does not support image or file attachments.",
        )

    def test_plain_hosted_async_turn_completes_without_codex(self) -> None:
        state = self.make_state()
        session = create_runtime_session(
            state.runtime_store,
            session_id="sess-plain",
            workspace_id="default",
            agent_id="chat",
            runtime_mode="plain_hosted_chat",
            start_path=state.repository_root,
        )

        with (
            patch.dict("os.environ", {"MAVERICK_HOSTED_TEXT_FAKE_RESPONSE": "async hosted"}, clear=False),
            patch("core.runtime.turn_submission_service_output.schedule_runtime_thread_title_generation"),
            patch(
                "core.runtime.turn_submission_service_runtime.resolve_runtime_backend_for_session",
                side_effect=AssertionError("agentic runtime should not be resolved"),
            ),
        ):
            turn, _events = submit_runtime_turn_async(state, session=session, input_text="Hello")
            for _ in range(100):
                current = state.runtime_store.get_turn(turn.turn_id)
                if current.status in {"completed", "failed"}:
                    break
                time.sleep(0.01)

        current = state.runtime_store.get_turn(turn.turn_id)
        self.assertEqual(current.status, "completed")
        event_types = [event.event_type for event in state.runtime_store.list_events(session.session_id)]
        self.assertIn("runtime.output.delta", event_types)
        self.assertNotIn("runtime.step.updated", event_types)
        self.assertIn("runtime.turn.completed", event_types)

    def test_plain_hosted_api_blocks_app_references_before_materialization(self) -> None:
        state = self.make_state()
        session = create_runtime_session(
            state.runtime_store,
            session_id="sess-plain",
            workspace_id="default",
            agent_id="chat",
            runtime_mode="plain_hosted_chat",
            start_path=state.repository_root,
        )
        context = SimpleNamespace(user=SimpleNamespace(user_id="user-1"), workspace_id="default")
        captured: dict[str, object] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            captured["status"] = status
            captured["headers"] = headers

        with patch("core.api.runtime_api.materialize_runtime_app_references_with_metrics") as materialize:
            body = _submit_runtime_turn_response(
                state,
                context,
                session,
                {"input_text": "hello", "app_references": [{"app_id": "storage"}]},
                start_response,
                start_path=state.repository_root,
            )

        payload = json.loads(b"".join(body).decode("utf-8"))
        self.assertEqual(captured["status"], "400 Bad Request")
        self.assertEqual(payload["error"], "plain_hosted_chat_blocks_app_references")
        materialize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
