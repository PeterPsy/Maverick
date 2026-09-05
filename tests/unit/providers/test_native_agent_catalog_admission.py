"""Negative probes for live native catalog and shared connection authority."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.agentic_models import default_actor_selection_policy
from core.providers.agentic_profiles import build_pinned_execution_binding
from core.providers.agentic_workspace_admin import save_workspace_agentic_binding
from core.providers.certificate_service import revoke_capability_certificate, validate_certificate_for_binding
from core.providers.errors import AgenticProfileError, CapabilityCertificateError
from core.providers.native_agent_catalog import native_agent_catalog_models
from core.providers.native_agent_contract import NativeAgentModelProviderConnection, validate_native_agent_installation
from core.providers.native_agent_discovery import discover_codex_native_catalog
from core.providers.native_agent_reconciliation import refresh_codex_native_catalog
from core.providers.native_agent_status import native_agent_status_items
from core.providers.provider_codex import CodexProviderAdapter
from core.providers.service import builtin_provider_registry, effective_provider_registry
from tests.support.maverick_agent_onboarding import provider_store
from tests.support.native_agent_catalog import codex_snapshot


class NativeAgentCatalogAdmissionTest(unittest.TestCase):
    def setUp(self):
        self.discovery = patch("core.providers.native_agent_reconciliation.discover_codex_native_catalog",
                               return_value=codex_snapshot("gpt-5.6-sol", "second-model"))
        self.discover = self.discovery.start()
        self.addCleanup(self.discovery.stop)
        self.store = provider_store()
        self.registry = effective_provider_registry(self.store, registry=builtin_provider_registry())

    def refresh(self, snapshot, **kwargs):
        self.discover.return_value = snapshot
        return refresh_codex_native_catalog(self.registry, store=self.store, force=True, **kwargs)

    def profile(self, model_id):
        return max((item for item in self.store.list_agentic_profile_definitions() if item.model_id == model_id),
                   key=lambda item: item.created_at)

    def bind(self, model_id):
        profile = self.profile(model_id)
        existing = next((item for item in self.store.list_workspace_agentic_profile_bindings("default")
                         if item.definition_id == profile.definition_id and item.definition_revision == profile.revision), None)
        return save_workspace_agentic_binding(
            self.store, self.registry, workspace_id="default", definition_id=profile.definition_id,
            definition_revision=profile.revision, credential_binding_id=None, enabled=True,
            is_default=False, actor_policy=default_actor_selection_policy(), policy_patch={},
            binding_id=None if existing is None else existing.binding_id,
            expected_revision=None if existing is None else existing.revision,
        )

    def pin(self, binding, **kwargs):
        return build_pinned_execution_binding(self.store, self.registry, session_id="test", workspace_id="default",
                                              execution_mode="sandbox", workspace_binding_id=binding.binding_id, **kwargs)

    def test_removal_blocks_binding_and_pin_but_not_connection(self):
        binding = self.bind("second-model")
        old_pin = self.pin(binding)
        self.refresh(codex_snapshot("gpt-5.6-sol"))
        with self.assertRaisesRegex(AgenticProfileError, "native_agent_model_unavailable"):
            self.pin(binding)
        with self.assertRaisesRegex(AgenticProfileError, "native_agent_model_unavailable"):
            self.bind("second-model")
        validate_certificate_for_binding(self.store, binding=old_pin,
                                         adapter=self.registry.get_agentic_runtime_adapter("codex"))

    def test_disabled_successor_is_not_reenabled_or_bypassed_by_a_later_revision(self):
        self.bind("second-model")
        self.refresh(codex_snapshot("gpt-5.6-sol", "second-model", reasoning=("low", "high")))
        profile = self.profile("second-model")
        rolled = next(item for item in self.store.list_workspace_agentic_profile_bindings("default")
                      if item.definition_revision == profile.revision)
        disabled = replace(rolled, enabled=False, revision=rolled.revision + 1, updated_at=datetime.now(tz=UTC))
        self.store.save_workspace_agentic_profile_binding(disabled, expected_revision=rolled.revision)
        self.refresh(codex_snapshot("gpt-5.6-sol", "second-model", "new-slug", reasoning=("low", "high")))
        self.assertEqual(self.store.get_workspace_agentic_profile_binding(rolled.binding_id), disabled)
        self.refresh(codex_snapshot("gpt-5.6-sol", "second-model", reasoning=("low", "medium", "high")))
        current = self.profile("second-model")
        self.assertFalse(any(item.enabled and item.definition_revision == current.revision
                             for item in self.store.list_workspace_agentic_profile_bindings("default")))


    def test_reasoning_change_publishes_new_content_addressed_revision(self):
        binding = self.bind("second-model")
        old = self.profile("second-model")
        old_certificate = self.store.get_capability_certificate(old.capability_certificate_id)
        self.refresh(codex_snapshot("gpt-5.6-sol", "second-model", reasoning=("low", "high")))
        current = self.profile("second-model")
        self.assertNotEqual(old.revision, current.revision)
        self.assertEqual(self.store.get_capability_certificate(old.capability_certificate_id), old_certificate)
        current_certificate = self.store.get_capability_certificate(current.capability_certificate_id)
        self.assertEqual(current_certificate.test_run_id, old_certificate.test_run_id)
        self.assertEqual(current_certificate.evidence_digest, old_certificate.evidence_digest)
        self.assertEqual(current_certificate.expires_at, old_certificate.expires_at)
        with self.assertRaisesRegex(AgenticProfileError, "native_agent_model_catalog_mismatch"):
            self.pin(binding)
        rolled = next(item for item in self.store.list_workspace_agentic_profile_bindings("default")
                      if item.definition_revision == current.revision)
        self.assertEqual(self.pin(rolled).certified_reasoning_efforts, ("low", "high"))

    def test_exact_revision_is_pinned_and_drift_blocks_admission(self):
        self.refresh(codex_snapshot("gpt-5.6-sol", "revisioned-model", revision="revision-one"))
        binding = self.bind("revisioned-model")
        pin = self.pin(binding)
        self.assertEqual((pin.model_revision, pin.model_revision_policy), ("revision-one", "exact"))
        self.refresh(codex_snapshot("gpt-5.6-sol", "revisioned-model", revision="revision-two"))
        with self.assertRaisesRegex(AgenticProfileError, "native_agent_model_catalog_mismatch"):
            self.pin(binding)

    def test_model_revocation_fences_new_slugs_via_shared_connection(self):
        old = self.profile("second-model")
        certificate = self.store.get_capability_certificate(old.capability_certificate_id)
        revoke_capability_certificate(self.store, certificate_id=certificate.certificate_id,
                                      expected_revision=0, reason="review_probe")
        self.refresh(codex_snapshot("gpt-5.6-sol", "second-model", "new-slug"))
        self.assertFalse(any(item.model_id == "new-slug" for item in self.store.list_capability_certificates()))
        with self.assertRaises(AgenticProfileError):
            self.bind("second-model")
        status = next(item for item in native_agent_status_items(self.registry, store=self.store)
                      if item["runtime_engine_id"] == "codex")
        self.assertFalse(status["selectable"])
        self.assertIn("revoked", status["unavailable_reason"])

    def test_expiry_cannot_be_renewed_by_a_new_slug(self):
        old = self.profile("second-model")
        certificate = self.store.get_capability_certificate(old.capability_certificate_id)
        binding = self.bind("second-model")
        future = certificate.expires_at + timedelta(seconds=1)
        self.refresh(codex_snapshot("gpt-5.6-sol", "second-model", "new-slug"), now=future)
        self.assertFalse(any(item.model_id == "new-slug" for item in self.store.list_capability_certificates()))
        with self.assertRaisesRegex(CapabilityCertificateError, "expired"):
            self.pin(binding, now=future)

    def test_projection_issuance_checks_now_not_the_old_profile_creation_date(self):
        from core.providers.builtin_certification import ensure_codex_preview_certificate

        old = self.profile("second-model")
        certificate = self.store.get_capability_certificate(old.capability_certificate_id)
        missing = replace(old, capability_certificate_id="must-not-be-issued")
        with self.assertRaisesRegex(CapabilityCertificateError, "connection_certificate_expired"):
            ensure_codex_preview_certificate(
                self.store, definition=missing,
                provider_definition=self.registry.get_provider_definition("codex"),
                adapter=self.registry.get_agentic_runtime_adapter("codex"),
                now=certificate.expires_at + timedelta(seconds=1),
            )
        self.assertFalse(any(
            item.certificate_id == missing.capability_certificate_id
            for item in self.store.list_capability_certificates()
        ))

    def test_catalog_expiry_and_failed_refresh_fail_closed(self):
        expired = replace(self.discover.return_value, expires_at=datetime.now(tz=UTC) - timedelta(seconds=1))
        self.registry.publish_native_agent_catalog(expired)
        installation = self.registry.get_native_agent_installation("codex")
        self.assertEqual(native_agent_catalog_models(self.registry, installation), ())
        self.refresh(None)
        self.assertEqual(native_agent_catalog_models(self.registry, installation), ())

    def test_partial_reconciliation_never_exposes_new_authority(self):
        with patch.object(self.store, "save_capability_certificate", side_effect=OSError("write failed")):
            with self.assertRaises(OSError):
                self.refresh(codex_snapshot("gpt-5.6-sol", "half-published"))
        self.assertIsNone(self.registry.get_native_agent_catalog("codex", "codex"))
        self.refresh(codex_snapshot("gpt-5.6-sol", "half-published"))
        self.pin(self.bind("half-published"))

    def test_duplicate_provider_to_foreign_catalog_mapping_is_rejected(self):
        installation = self.registry.get_native_agent_installation("codex")
        with self.assertRaisesRegex(ValueError, "connection_duplicate"):
            validate_native_agent_installation(replace(installation, model_provider_connections=(
                NativeAgentModelProviderConnection("codex", "codex"),
                NativeAgentModelProviderConnection("codex", "openrouter"),
            )))

    def test_version_success_does_not_authorize_failed_catalog(self):
        with tempfile.TemporaryDirectory() as folder:
            command = Path(folder) / "fake-native"
            command.write_text('#!/bin/sh\nif [ "$1" = "--version" ]; then echo "codex-cli test"; exit 0; fi\nexit 1\n')
            command.chmod(0o755)
            self.assertIsNone(discover_codex_native_catalog(CodexProviderAdapter(codex_command=str(command)), force=True))

    def test_discovery_preserves_verified_exact_and_explicit_alias_revisions(self):
        with tempfile.TemporaryDirectory() as folder:
            command = Path(folder) / "fake-native"
            command.write_text("#!/bin/sh\n")
            adapter = CodexProviderAdapter(codex_command=str(command))
            for policy in ("exact", "provider_alias"):
                payload = {"models": [{
                    "visibility": "list", "slug": "revisioned-model",
                    "model_revision": "release-1", "revision_policy": policy,
                }]}
                with self.subTest(policy=policy), patch(
                    "core.providers.native_agent_discovery.subprocess.run",
                    return_value=SimpleNamespace(stdout=json.dumps(payload)),
                ):
                    snapshot = discover_codex_native_catalog(adapter, force=True)
                    self.assertIsNotNone(snapshot)
                    self.assertEqual(snapshot.models[0].model_revision, "release-1")
                    self.assertEqual(snapshot.models[0].revision_policy, policy)
                    self.assertEqual(snapshot.model_options[0].metadata["model_revision"], "release-1")

    def test_discovery_rejects_unverified_exact_revision_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            command = Path(folder) / "fake-native"
            command.write_text("#!/bin/sh\n")
            adapter = CodexProviderAdapter(codex_command=str(command))
            for revision in (None, "", " padded "):
                payload = {"models": [{
                    "visibility": "list", "slug": "revisioned-model",
                    "model_revision": revision, "revision_policy": "exact",
                }]}
                with self.subTest(revision=revision), patch(
                    "core.providers.native_agent_discovery.subprocess.run",
                    return_value=SimpleNamespace(stdout=json.dumps(payload)),
                ):
                    self.assertIsNone(discover_codex_native_catalog(adapter, force=True))

    def test_shared_revocation_is_checked_by_the_fast_authority_path(self):
        from core.runtime.authority_service import revalidate_runtime_authority_snapshot

        pin = self.pin(self.bind("second-model"))
        projection = self.store.get_capability_certificate(pin.capability_certificate_id)
        revoke_capability_certificate(self.store, certificate_id=projection.native_connection_certificate_id,
                                      expected_revision=0, reason="connection_revoked")
        self.assertEqual(self.store.get_capability_certificate_status(projection.certificate_id).status, "active")
        with self.assertRaisesRegex(CapabilityCertificateError, "connection_certificate_revoked"):
            revalidate_runtime_authority_snapshot(
                SimpleNamespace(provider_store=self.store), session=SimpleNamespace(execution_binding=pin),
                adapter=self.registry.get_agentic_runtime_adapter("codex"),
                authority=SimpleNamespace(execution_binding_id=pin.execution_binding_id, certificate_id=projection.certificate_id),
            )

    def test_legacy_revoked_certificate_is_adopted_without_resetting_revocation(self):
        from core.providers.builtin_certification import ensure_codex_preview_certificate
        from core.providers.certificate_service import publish_capability_certificate

        old = self.profile("second-model")
        projected = self.store.get_capability_certificate(old.capability_certificate_id)
        legacy_store = provider_store()
        legacy = replace(projected, native_connection_certificate_id="", native_connection_identity_digest="")
        publish_capability_certificate(legacy_store, certificate=legacy,
                                      evidence=self.store.get_capability_evidence(legacy.evidence_digest))
        revoke_capability_certificate(legacy_store, certificate_id=legacy.certificate_id,
                                      expected_revision=0, reason="legacy_revocation")
        current = replace(old, model_id="gpt-5.6-sol", capability_certificate_id="new-model-projection")
        with self.assertRaisesRegex(CapabilityCertificateError, "connection_certificate_revoked"):
            ensure_codex_preview_certificate(
                legacy_store, definition=current, provider_definition=self.registry.get_provider_definition("codex"),
                adapter=self.registry.get_agentic_runtime_adapter("codex"),
            )
        root = next(item for item in legacy_store.list_capability_certificates() if item.certificate_scope == "native_connection")
        self.assertEqual(root.expires_at, legacy.expires_at)
        self.assertEqual(root.evidence_digest, legacy.evidence_digest)
        self.assertEqual(root.legacy_projection_certificate_ids, (legacy.certificate_id,))
        self.assertEqual(legacy_store.get_capability_certificate_status(root.certificate_id).status, "revoked")

    def test_empty_catalog_preserves_the_legacy_connection_for_existing_pins(self):
        from core.providers.certificate_service import publish_capability_certificate

        pin = self.pin(self.bind("second-model"))
        profile = self.profile("second-model")
        projection = self.store.get_capability_certificate(profile.capability_certificate_id)
        legacy = replace(projection, native_connection_certificate_id="", native_connection_identity_digest="")
        legacy_store = provider_store()
        legacy_store.save_agentic_profile_definition(profile)
        publish_capability_certificate(
            legacy_store, certificate=legacy,
            evidence=self.store.get_capability_evidence(legacy.evidence_digest),
        )
        self.discover.return_value = codex_snapshot()
        effective_provider_registry(legacy_store, registry=self.registry, refresh_model_catalog=True)
        self.assertEqual(native_agent_catalog_models(
            self.registry, self.registry.get_native_agent_installation("codex"),
        ), ())
        validate_certificate_for_binding(
            legacy_store, binding=pin, adapter=self.registry.get_agentic_runtime_adapter("codex"),
        )


if __name__ == "__main__":
    unittest.main()
