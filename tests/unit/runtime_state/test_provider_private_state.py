from __future__ import annotations

from datetime import UTC, datetime
import json
import unittest

from core.providers.agentic_models import codex_routing_constraint, codex_runtime_policy
from core.runtime.execution_binding import build_runtime_execution_binding
from core.runtime.private_payload_store import EncryptedRuntimePrivatePayloadStore
from core.runtime.provider_private_state import (
    ProviderPrivateStateError,
    ProviderPrivateStateService,
)
from core.runtime.provider_state import RuntimeProviderState
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 8, 16, tzinfo=UTC)
KEY = bytes(range(32))


class ProviderPrivateStateServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_repo_root(self)
        self.store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                provider_states=FakeCollection(),
            )
        )
        self.binding = build_runtime_execution_binding(
            session_id="session-private",
            workspace_id="default",
            profile_definition_id="profile-fake",
            profile_definition_revision="1",
            workspace_binding_id="binding-fake",
            workspace_binding_revision=0,
            capability_certificate_id="certificate-fake",
            certificate_evidence_digest="a" * 64,
            runtime_engine_id="fake-hosted-engine",
            adapter_id="fake-hosted-adapter",
            adapter_version="1.2.3",
            adapter_artifact_digest="b" * 64,
            model_provider_id="fake-provider",
            model_id="fake-model",
            provider_protocol="fake-v1",
            provider_api_version="v1",
            routing_constraint=codex_routing_constraint(),
            credential_binding_id=None,
            reasoning_effort=None,
            certified_reasoning_efforts=(),
            default_reasoning_effort=None,
            execution_mode="full-access",
            profile_policy_ceiling=codex_runtime_policy(),
            workspace_policy_ceiling=codex_runtime_policy(),
            egress_policy_id="fake-only",
            egress_policy_revision="1",
            created_at=NOW,
        )
        self.session = RuntimeSessionRecord(
            session_id="session-private",
            workspace_id="default",
            agent_id="chat",
            status="running",
            requested_mode="full-access",
            effective_mode="full-access",
            workspace_root="/workspace",
            workdir="/workspace",
            runtime_root="/runtime/session-private",
            started_at=NOW,
            updated_at=NOW,
            ended_at=None,
            last_progress_at=NOW,
            execution_binding=self.binding,
        )
        self.store.insert_session(self.session)
        self.store.initialize_provider_state(
            RuntimeProviderState(
                session_id=self.session.session_id,
                workspace_id=self.session.workspace_id,
                runtime_engine_id=self.binding.runtime_engine_id,
                model_provider_id=self.binding.model_provider_id,
                continuation_id=None,
                provider_thread_id=None,
                provider_request_id=None,
                provider_private_envelope=None,
                revision=0,
                turn_generation=None,
                updated_at=NOW,
            )
        )
        self.service = self._service()

    def _service(self) -> ProviderPrivateStateService:
        payload_store = EncryptedRuntimePrivatePayloadStore(
            repository_root=self.root,
            key_loader=lambda: KEY,
        )
        return ProviderPrivateStateService(store=self.store, payload_store=payload_store)

    def _store_signature(self, signature: bytes = b"opaque-thought-signature-never-public"):
        return self.service.store_state(
            session_id=self.session.session_id,
            adapter_id=self.binding.adapter_id,
            adapter_version=self.binding.adapter_version,
            codec_id="fake-thought-codec",
            codec_version="2",
            schema_version="1",
            content_type="application/vnd.fake.private-state",
            payload=signature,
            expected_revision=0,
            turn_generation="turn-generation-1",
            now=NOW,
        )

    def test_exact_private_state_round_trips_after_restart_without_plaintext_on_disk(self) -> None:
        signature = b"opaque-thought-signature-never-public"
        state = self._store_signature(signature)

        restarted_service = self._service()
        restored = restarted_service.read_state(
            session_id=self.session.session_id,
            adapter_id=self.binding.adapter_id,
            adapter_version=self.binding.adapter_version,
            codec_id="fake-thought-codec",
            codec_version="2",
            schema_version="1",
            purpose="recovery",
        )

        self.assertEqual(restored, signature)
        self.assertNotIn(signature.decode(), json.dumps(state, default=str))
        private_files = list(self.root.glob("workspaces/default/runtime/sessions/session-private/private/**/*.json"))
        self.assertEqual(len(private_files), 1)
        self.assertNotIn(signature, private_files[0].read_bytes())

    def test_wrong_adapter_or_codec_fails_closed(self) -> None:
        self._store_signature()

        with self.assertRaisesRegex(ProviderPrivateStateError, "adapter_mismatch"):
            self.service.read_state(
                session_id=self.session.session_id,
                adapter_id="other-adapter",
                adapter_version=self.binding.adapter_version,
                codec_id="fake-thought-codec",
                codec_version="2",
                schema_version="1",
            )
        with self.assertRaisesRegex(ProviderPrivateStateError, "codec_mismatch"):
            self.service.read_state(
                session_id=self.session.session_id,
                adapter_id=self.binding.adapter_id,
                adapter_version=self.binding.adapter_version,
                codec_id="fake-thought-codec",
                codec_version="3",
                schema_version="1",
            )

    def test_ciphertext_tamper_and_stale_revision_fail_explicitly(self) -> None:
        self._store_signature()
        private_file = next(
            self.root.glob("workspaces/default/runtime/sessions/session-private/private/**/*.json")
        )
        document = json.loads(private_file.read_text(encoding="utf-8"))
        document["ciphertext"] = document["ciphertext"][:-2] + "AA"
        private_file.write_text(json.dumps(document), encoding="utf-8")

        with self.assertRaisesRegex(ProviderPrivateStateError, "integrity_failed"):
            self.service.read_state(
                session_id=self.session.session_id,
                adapter_id=self.binding.adapter_id,
                adapter_version=self.binding.adapter_version,
                codec_id="fake-thought-codec",
                codec_version="2",
                schema_version="1",
            )
        with self.assertRaisesRegex(ProviderPrivateStateError, "revision_stale"):
            self._store_signature(b"second-value")

    def test_empty_and_oversized_payloads_are_rejected(self) -> None:
        for payload in (b"", b"x" * (2 * 1_048_576 + 1)):
            with self.subTest(size=len(payload)):
                with self.assertRaises(ProviderPrivateStateError):
                    self._store_signature(payload)


if __name__ == "__main__":
    unittest.main()
