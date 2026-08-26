from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import json
from types import SimpleNamespace
import unittest

from core.providers.agentic_models import codex_routing_constraint, codex_runtime_policy
from core.providers.agentic_protocol import AgenticSourceMetadata
from core.runtime.execution_binding import build_runtime_execution_binding
from core.runtime.hosted_agentic_models import HostedProviderPrivateCodec
from core.runtime.hosted_agentic_state import HostedAgenticStateBridge
from core.runtime.private_payload_store import EncryptedRuntimePrivatePayloadStore
from core.runtime.provider_private_state import (
    ProviderPrivateStateError,
    ProviderPrivateStateService,
)
from core.runtime.provider_state import RuntimeProviderState, runtime_provider_state_from_document
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

    def test_taint_metadata_survives_persist_load_and_is_never_private_content(self) -> None:
        source_metadata = (
            AgenticSourceMetadata(
                source_block_digest="1" * 64,
                source_data_class="public",
                source_trust_level="trusted_platform",
                provenance="tool_schema",
            ),
            AgenticSourceMetadata(
                source_block_digest="2" * 64,
                source_data_class="personal_data",
                source_trust_level="untrusted_tool_output",
                provenance="tool_result",
            ),
        )

        state = self.service.store_state(
            session_id=self.session.session_id,
            adapter_id=self.binding.adapter_id,
            adapter_version=self.binding.adapter_version,
            codec_id="fake-thought-codec",
            codec_version="2",
            schema_version="1",
            content_type="application/vnd.fake.private-state",
            payload=b"private-provider-continuation",
            expected_revision=0,
            turn_generation="turn-generation-7",
            source_metadata=source_metadata,
            provider_request_id="provider-request-7",
            now=NOW,
        )

        envelope = state.provider_private_envelope
        assert envelope is not None
        self.assertEqual(envelope.source_block_digests, ("1" * 64, "2" * 64))
        self.assertEqual(envelope.source_data_classes, ("public", "personal_data"))
        self.assertEqual(
            envelope.source_trust_levels,
            ("trusted_platform", "untrusted_tool_output"),
        )
        self.assertEqual(envelope.effective_data_class, "personal_data")
        self.assertEqual(envelope.effective_trust_level, "untrusted_tool_output")
        self.assertEqual(envelope.codec_identity, "fake-thought-codec:2:1")
        self.assertEqual(envelope.provider_request_id, "provider-request-7")
        self.assertEqual(envelope.turn_generation, "turn-generation-7")
        reloaded = runtime_provider_state_from_document(asdict(state))
        self.assertEqual(reloaded, state)
        serialized = json.dumps(asdict(reloaded), default=str)
        self.assertNotIn("private-provider-continuation", serialized)

        continuation = HostedAgenticStateBridge(
            service=self._service(),
            codec=HostedProviderPrivateCodec(
                codec_id="fake-thought-codec",
                codec_version="2",
                schema_version="1",
                content_type="application/vnd.fake.private-state",
            ),
        ).read(
            SimpleNamespace(session=self.session, binding=self.binding),
            SimpleNamespace(
                allowed_capabilities=SimpleNamespace(provider_private_state=True)
            ),
        )
        assert continuation is not None
        self.assertEqual(continuation.content, b"private-provider-continuation")
        self.assertEqual(continuation.effective_data_class, "personal_data")
        self.assertEqual(
            tuple(item.source_data_class for item in continuation.source_metadata),
            ("public", "personal_data"),
        )
        self.assertEqual(continuation.provider_request_id, "provider-request-7")
        self.assertEqual(continuation.turn_generation, "turn-generation-7")

    def test_missing_or_invalid_taint_metadata_serializes_fail_closed(self) -> None:
        state = self.service.store_state(
            session_id=self.session.session_id,
            adapter_id=self.binding.adapter_id,
            adapter_version=self.binding.adapter_version,
            codec_id="fake-thought-codec",
            codec_version="2",
            schema_version="1",
            content_type="application/vnd.fake.private-state",
            payload=b"legacy-private-state",
            expected_revision=0,
            turn_generation="turn-generation-1",
            source_metadata=(
                AgenticSourceMetadata(
                    source_block_digest="browser-digest",
                    source_data_class="public",
                    source_trust_level="trusted_platform",
                    provenance="browser",
                ),
            ),
            now=NOW,
        )

        envelope = state.provider_private_envelope
        assert envelope is not None
        self.assertEqual(envelope.source_block_digests, ())
        self.assertEqual(envelope.source_data_classes, ("unclassified",))
        self.assertEqual(envelope.effective_data_class, "unclassified")


if __name__ == "__main__":
    unittest.main()
