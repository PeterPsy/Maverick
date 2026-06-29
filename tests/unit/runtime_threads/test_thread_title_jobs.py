"""Tests for runtime thread title jobs and deterministic fallbacks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import signal
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.service import activate_hosted_model_provider
from core.providers.store import ProviderCollections, ProviderDocumentStore
from core.providers.text_generation import TextGenerationResult
from core.runtime.runtime_threads import create_runtime_thread, update_runtime_thread
from core.runtime.service import create_runtime_session
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.thread_title_jobs import (
    ThreadTitleGenerationError,
    ThreadTitleGenerationResult,
    _run_codex_title_command,
    fallback_thread_title,
    generate_ai_thread_title,
    generate_hosted_thread_title,
    normalize_ai_thread_title,
    run_runtime_thread_title_generation,
    thread_title_input_hash,
)
from core.runtime.thread_titles import DEFAULT_THREAD_TITLE
from core.secrets.service import build_secret_ref, create_platform_secret
from core.secrets.store import SecretCollections, SecretDocumentStore
from tests.support.collections import FakeCollection


class RuntimeThreadTitleJobTest(unittest.TestCase):
    def make_store(self) -> RuntimeDocumentStore:
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

    def make_provider_store(self) -> ProviderDocumentStore:
        return ProviderDocumentStore(
            ProviderCollections(
                definitions=FakeCollection(),
                bindings=FakeCollection(),
                selections=FakeCollection(),
                hosted_selections=FakeCollection(),
            )
        )

    def make_secret_store(self) -> SecretDocumentStore:
        return SecretDocumentStore(
            SecretCollections(
                secrets=FakeCollection(),
                values=FakeCollection(),
                bindings=FakeCollection(),
                grants=FakeCollection(),
            ),
            key_loader=lambda: b"test-key-material-for-thread-titles",
        )

    def make_hosted_title_state(self):
        provider_store = self.make_provider_store()
        secret_store = self.make_secret_store()
        secret = create_platform_secret(
            secret_store,
            label="OpenRouter title tests",
            raw_value="super-secret-token",
            alias="openrouter-title-test",
            kind="api_key",
        )
        activate_hosted_model_provider(
            provider_store,
            secret_store=secret_store,
            workspace_id="acme",
            provider_id="openrouter",
            secret_ref=build_secret_ref(alias=secret.alias or "openrouter-title-test"),
        )
        return SimpleNamespace(
            provider_store=provider_store,
            secret_store=secret_store,
            workspace_root="/tmp/acme",
        )

    def test_ai_title_job_completes_pending_thread_title(self) -> None:
        store = self.make_store()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        message = "analizza il budget vendite mensili del cliente Rossi"
        input_hash = thread_title_input_hash(message)
        create_runtime_session(store, session_id="session-a", workspace_id="acme", agent_id="chat", now=now)
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title=DEFAULT_THREAD_TITLE,
            title_pending=True,
            title_source="pending",
            title_generation_input_hash=input_hash,
            now=now,
        )
        state = SimpleNamespace(runtime_store=store, runtime_thread_event_bus=None)

        updated = run_runtime_thread_title_generation(
            state=state,
            workspace_id="acme",
            runtime_session_id="session-a",
            title_generation_input_hash=input_hash,
            input_text=message,
            title_generator=lambda **_: "Analisi Budget Vendite Mensili",
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.title, "Analisi Budget Vendite Mensili")
        self.assertFalse(updated.title_pending)
        self.assertEqual(updated.title_source, "ai")
        self.assertIsNone(updated.title_generation_failure)
        self.assertEqual(updated.title_generation_provider_id, "")
        self.assertEqual(updated.title_generation_model_id, "")

    def test_ai_title_job_accepts_short_specific_title(self) -> None:
        self.assertEqual(normalize_ai_thread_title("Chi Sei"), "Chi Sei")

    def test_ai_title_job_persists_generation_provider_metadata(self) -> None:
        store = self.make_store()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        message = "analizza il budget vendite mensili del cliente Rossi"
        input_hash = thread_title_input_hash(message)
        create_runtime_session(store, session_id="session-a", workspace_id="acme", agent_id="chat", now=now)
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title=DEFAULT_THREAD_TITLE,
            title_pending=True,
            title_source="pending",
            title_generation_input_hash=input_hash,
            now=now,
        )
        state = SimpleNamespace(runtime_store=store, runtime_thread_event_bus=None)

        updated = run_runtime_thread_title_generation(
            state=state,
            workspace_id="acme",
            runtime_session_id="session-a",
            title_generation_input_hash=input_hash,
            input_text=message,
            title_generator=lambda **_: ThreadTitleGenerationResult(
                title="Analisi Budget Vendite",
                provider_id="openrouter",
                model_id="google/gemma-4-31b-it:free",
            ),
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.title, "Analisi Budget Vendite")
        self.assertEqual(updated.title_generation_provider_id, "openrouter")
        self.assertEqual(updated.title_generation_model_id, "google/gemma-4-31b-it:free")

    def test_ai_title_job_falls_back_to_deterministic_title_when_model_title_is_invalid(self) -> None:
        store = self.make_store()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        message = "analizza il budget vendite mensili del cliente Rossi"
        input_hash = thread_title_input_hash(message)
        create_runtime_session(store, session_id="session-a", workspace_id="acme", agent_id="chat", now=now)
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title=DEFAULT_THREAD_TITLE,
            title_pending=True,
            title_source="pending",
            title_generation_input_hash=input_hash,
            now=now,
        )
        state = SimpleNamespace(runtime_store=store, runtime_thread_event_bus=None)

        updated = run_runtime_thread_title_generation(
            state=state,
            workspace_id="acme",
            runtime_session_id="session-a",
            title_generation_input_hash=input_hash,
            input_text=message,
            title_generator=lambda **_: "Budget",
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertFalse(updated.title_pending)
        self.assertEqual(updated.title_source, "deterministic")
        self.assertEqual(updated.title, fallback_thread_title(message))
        self.assertTrue(updated.title_generation_failure)

    def test_hosted_title_generation_uses_openrouter_gemma_fast_model(self) -> None:
        state = self.make_hosted_title_state()
        captured = {}

        def fake_execute(provider_store, secret_store, *, decision, request, app_id=None, **kwargs):
            captured["decision"] = decision
            captured["request"] = request
            captured["app_id"] = app_id
            return TextGenerationResult(
                output_text='{"title":"Analisi Budget Vendite"}',
                deltas=['{"title":"Analisi Budget Vendite"}'],
                provider_id=decision.selected_provider_id or "",
                model_id=request.model_id,
            )

        with patch("core.runtime.thread_title_jobs.execute_hosted_text_generation", side_effect=fake_execute):
            result = generate_hosted_thread_title(
                state=state,
                workspace_id="acme",
                input_text="analizza il budget vendite mensili del cliente Rossi",
            )

        self.assertEqual(result.title, "Analisi Budget Vendite")
        self.assertEqual(result.provider_id, "openrouter")
        self.assertEqual(result.model_id, "google/gemma-4-31b-it:free")
        self.assertEqual(captured["decision"].selected_provider_id, "openrouter")
        self.assertEqual(captured["request"].model_id, "google/gemma-4-31b-it:free")
        self.assertEqual(captured["request"].max_output_tokens, 80)
        self.assertEqual(captured["app_id"], "chat")

    def test_ai_title_generation_falls_back_to_codex_when_hosted_profile_unavailable(self) -> None:
        state = SimpleNamespace(provider_store=self.make_provider_store(), secret_store=self.make_secret_store())

        with patch(
            "core.runtime.thread_title_jobs.generate_codex_thread_title",
            return_value=ThreadTitleGenerationResult(title="Fallback Codex Title", provider_id="codex", model_id="gpt-5.5"),
        ) as codex:
            result = generate_ai_thread_title(
                state=state,
                workspace_id="acme",
                input_text="analizza il budget vendite mensili del cliente Rossi",
            )

        self.assertEqual(result.title, "Fallback Codex Title")
        self.assertEqual(result.provider_id, "codex")
        self.assertEqual(result.model_id, "gpt-5.5")
        codex.assert_called_once()

    def test_ai_title_generation_falls_back_to_codex_when_hosted_returns_invalid_json(self) -> None:
        state = self.make_hosted_title_state()

        with (
            patch(
                "core.runtime.thread_title_jobs.execute_hosted_text_generation",
                return_value=TextGenerationResult(
                    output_text="not json",
                    deltas=["not json"],
                    provider_id="openrouter",
                    model_id="google/gemma-4-31b-it:free",
                ),
            ),
            patch(
                "core.runtime.thread_title_jobs.generate_codex_thread_title",
                return_value=ThreadTitleGenerationResult(title="Fallback Codex Title", provider_id="codex", model_id="gpt-5.5"),
            ) as codex,
        ):
            result = generate_ai_thread_title(
                state=state,
                workspace_id="acme",
                input_text="analizza il budget vendite mensili del cliente Rossi",
            )

        self.assertEqual(result.title, "Fallback Codex Title")
        self.assertEqual(result.provider_id, "codex")
        self.assertEqual(result.model_id, "gpt-5.5")
        codex.assert_called_once()

    def test_ai_title_job_does_not_overwrite_manual_rename(self) -> None:
        store = self.make_store()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        message = "analizza il budget vendite mensili del cliente Rossi"
        input_hash = thread_title_input_hash(message)
        create_runtime_session(store, session_id="session-a", workspace_id="acme", agent_id="chat", now=now)
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title=DEFAULT_THREAD_TITLE,
            title_pending=True,
            title_source="pending",
            title_generation_input_hash=input_hash,
            now=now,
        )
        update_runtime_thread(
            store,
            thread_id="thread-a",
            workspace_id="acme",
            updates={"title": "Titolo scelto manualmente"},
            now=now + timedelta(seconds=1),
        )
        state = SimpleNamespace(runtime_store=store, runtime_thread_event_bus=None)

        updated = run_runtime_thread_title_generation(
            state=state,
            workspace_id="acme",
            runtime_session_id="session-a",
            title_generation_input_hash=input_hash,
            input_text=message,
            title_generator=lambda **_: "Analisi Budget Vendite Mensili",
        )

        self.assertIsNone(updated)
        thread = store.get_thread("thread-a")
        self.assertEqual(thread.title, "Titolo scelto manualmente")
        self.assertFalse(thread.title_pending)
        self.assertEqual(thread.title_source, "manual")

    def test_ai_title_command_timeout_terminates_process_group(self) -> None:
        class TimeoutProcess:
            pid = 1234
            args = ["codex"]
            returncode = None

            def __init__(self) -> None:
                self.input_text = ""
                self.wait_timeout = None

            def communicate(self, *, input: str | None = None, timeout: int | None = None) -> tuple[str, str]:
                self.input_text = input or ""
                raise subprocess.TimeoutExpired(self.args, timeout)

            def poll(self) -> int | None:
                return self.returncode

            def wait(self, *, timeout: float | None = None) -> int:
                self.wait_timeout = timeout
                self.returncode = -signal.SIGTERM
                return self.returncode

            def terminate(self) -> None:
                self.returncode = -signal.SIGTERM

            def kill(self) -> None:
                self.returncode = -signal.SIGKILL

        process = TimeoutProcess()

        with patch("core.runtime.thread_title_jobs.subprocess.Popen", return_value=process) as popen, patch(
            "core.runtime.thread_title_jobs.os.killpg"
        ) as killpg:
            with self.assertRaises(ThreadTitleGenerationError):
                _run_codex_title_command(["codex", "exec"], prompt="title prompt", timeout_seconds=3)

        self.assertEqual(process.input_text, "title prompt")
        self.assertEqual(process.wait_timeout, 1.0)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        killpg.assert_called_once_with(1234, signal.SIGTERM)

if __name__ == "__main__":
    unittest.main()
