from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from core.providers.hosted_text_profiles import (
    hosted_text_binding_from_document,
    pin_hosted_text_execution_binding,
)
from core.providers.provider_credentials import bind_provider_credential
from core.providers.service import builtin_provider_registry, register_builtin_providers
from core.providers.store import ProviderCollections, ProviderDocumentStore
from core.providers.text_generation import HostedTextGenerationError
from core.api.runtime_api import _session_payload
from core.runtime.errors import RuntimeProviderStateError
from core.runtime.plain_hosted_text import execute_plain_hosted_text_turn
from core.runtime.runtime_session import runtime_session_from_document
from core.runtime.service import create_runtime_session
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.secrets.service import build_secret_ref, create_platform_secret
from core.secrets.store import SecretCollections, SecretDocumentStore
from tests.support.collections import FakeCollection


NOW = datetime(2026, 9, 4, tzinfo=UTC)


class HostedTextProfilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider_store = ProviderDocumentStore(
            ProviderCollections(
                definitions=FakeCollection(),
                bindings=FakeCollection(),
                selections=FakeCollection(),
            )
        )
        register_builtin_providers(self.provider_store)
        registry = builtin_provider_registry()
        openrouter = registry.get_provider_definition("openrouter")
        self.provider_store.save_provider_definition(
            replace(openrouter, status="active")
        )
        self.secret_store = SecretDocumentStore(
            SecretCollections(
                secrets=FakeCollection(),
                values=FakeCollection(),
                bindings=FakeCollection(),
                grants=FakeCollection(),
            ),
            key_loader=lambda: b"hosted-text-profile-test-key",
        )
        secret = create_platform_secret(
            self.secret_store,
            label="OpenRouter",
            raw_value="secret",
            alias="hosted-text-profile-key",
            kind="api_key",
        )
        bind_provider_credential(
            self.provider_store,
            provider_id="openrouter",
            workspace_id="default",
            secret_ref=build_secret_ref(alias=secret.alias),
        )
        self.runtime_store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                provider_states=FakeCollection(),
                provider_step_journals=FakeCollection(),
            )
        )
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name in ("core", "apps", "workspaces", "scripts"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        (self.root / "docs" / "architecture").mkdir(parents=True)
        (self.root / "AGENTS.md").write_text("", encoding="utf-8")
        self.state = SimpleNamespace(
            provider_store=self.provider_store,
            provider_registry=registry,
            secret_store=self.secret_store,
            runtime_store=self.runtime_store,
            observability_store=None,
        )

    def pin(self, *, session_id: str = "text-session"):
        return pin_hosted_text_execution_binding(
            self.state,
            session_id=session_id,
            workspace_id="default",
            hosted_provider_id="openrouter",
            hosted_model_id="google/gemma-4-31b-it:free",
            now=NOW,
        )

    def test_profile_status_and_certificate_are_text_only_records(self) -> None:
        binding = self.pin()

        self.assertEqual(binding.profile.execution_family, "hosted_text")
        self.assertEqual(binding.status.status, "available")
        self.assertEqual(binding.certificate.certificate_kind, "hosted_text_capability")
        self.assertFalse(binding.certificate.workspace_tools)
        self.assertFalse(binding.certificate.action_loop)
        self.assertFalse(binding.certificate.workspace_actions)
        self.assertNotIn("capability-certificate:", binding.certificate.certificate_id)

    def test_binding_round_trips_and_rejects_profile_tampering(self) -> None:
        binding = self.pin()
        document = asdict(binding)

        self.assertEqual(hosted_text_binding_from_document(document), binding)
        document["profile"]["model_id"] = "silently-changed-model"
        with self.assertRaisesRegex(ValueError, "identity is invalid"):
            hosted_text_binding_from_document(document)

    def test_session_pin_creates_no_agent_provider_state_or_step_journal(self) -> None:
        binding = self.pin()
        session = create_runtime_session(
            self.runtime_store,
            session_id=binding.session_id,
            workspace_id="default",
            agent_id="chat",
            runtime_mode="plain_hosted_chat",
            hosted_text_binding=binding,
            start_path=self.root,
            now=NOW,
        )
        stored = self.runtime_store.get_session(session.session_id)

        self.assertEqual(stored.hosted_text_binding, binding)
        self.assertEqual(stored.hosted_provider_id, binding.provider_id)
        self.assertEqual(stored.hosted_model_id, binding.model_id)
        payload = _session_payload(stored)
        self.assertEqual(payload["execution_family"], "hosted_text")
        self.assertEqual(
            payload["hosted_text_profile"]["message"],
            "No workspace tools or actions.",
        )
        self.assertFalse(
            payload["hosted_text_profile"]["certificate"]["workspace_actions"]
        )
        self.assertEqual(
            self.runtime_store.list_provider_step_journals(
                session_id=session.session_id
            ),
            [],
        )
        with self.assertRaises(RuntimeProviderStateError):
            self.runtime_store.get_provider_state(session.session_id)

    def test_session_family_and_route_cannot_be_changed_implicitly(self) -> None:
        binding = self.pin()
        with self.assertRaisesRegex(ValueError, "cannot carry text-only"):
            create_runtime_session(
                self.runtime_store,
                session_id=binding.session_id,
                workspace_id="default",
                agent_id="chat",
                runtime_mode="agentic",
                hosted_text_binding=binding,
                start_path=self.root,
                now=NOW,
            )
        with self.assertRaisesRegex(ValueError, "does not match"):
            create_runtime_session(
                self.runtime_store,
                session_id=binding.session_id,
                workspace_id="default",
                agent_id="chat",
                runtime_mode="plain_hosted_chat",
                hosted_provider_id="google-ai-studio",
                hosted_text_binding=binding,
                start_path=self.root,
                now=NOW,
            )

    def test_dispatch_fails_instead_of_falling_back_from_pinned_provider(self) -> None:
        binding = self.pin()
        session = create_runtime_session(
            self.runtime_store,
            session_id=binding.session_id,
            workspace_id="default",
            agent_id="chat",
            runtime_mode="plain_hosted_chat",
            hosted_text_binding=binding,
            start_path=self.root,
            now=NOW,
        )
        current = self.provider_store.get_provider_definition("openrouter")
        self.provider_store.save_provider_definition(replace(current, status="disabled"))
        google = self.provider_store.get_provider_definition("google-ai-studio")
        self.provider_store.save_provider_definition(replace(google, status="active"))

        with self.assertRaises(HostedTextGenerationError):
            execute_plain_hosted_text_turn(
                self.state,
                session=session,
                input_text="Do not change provider",
            )

    def test_successful_text_dispatch_still_creates_no_agent_journal(self) -> None:
        binding = self.pin()
        session = create_runtime_session(
            self.runtime_store,
            session_id=binding.session_id,
            workspace_id="default",
            agent_id="chat",
            runtime_mode="plain_hosted_chat",
            hosted_text_binding=binding,
            start_path=self.root,
            now=NOW,
        )

        with patch.dict(
            "os.environ",
            {"MAVERICK_HOSTED_TEXT_FAKE_RESPONSE": "text only"},
            clear=False,
        ):
            result, decision = execute_plain_hosted_text_turn(
                self.state,
                session=session,
                input_text="Hello",
            )

        self.assertEqual(result.output_text, "text only")
        self.assertEqual(decision.selected_provider_id, binding.provider_id)
        self.assertEqual(
            self.runtime_store.list_provider_step_journals(
                session_id=session.session_id
            ),
            [],
        )
        with self.assertRaises(RuntimeProviderStateError):
            self.runtime_store.get_provider_state(session.session_id)

    def test_legacy_text_session_hydrates_without_rewriting_a_pin(self) -> None:
        document = {
            "session_id": "legacy-text-session",
            "workspace_id": "default",
            "agent_id": "chat",
            "status": "running",
            "requested_mode": None,
            "effective_mode": "sandbox",
            "workspace_root": "/workspace",
            "workdir": "/workspace",
            "runtime_root": "/runtime/legacy-text-session",
            "started_at": NOW,
            "updated_at": NOW,
            "ended_at": None,
            "last_progress_at": NOW,
            "runtime_mode": "plain_hosted_chat",
            "hosted_provider_id": "openrouter",
            "hosted_model_id": "legacy-model",
        }

        session = runtime_session_from_document(document)

        self.assertIsNone(session.hosted_text_binding)
        self.assertEqual(session.hosted_model_id, "legacy-model")


if __name__ == "__main__":
    unittest.main()
