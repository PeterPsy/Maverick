"""Regression matrix for post-publication target substitution (both API providers)."""

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from threading import RLock
from types import SimpleNamespace
from unittest import TestCase, mock

from core.providers.agentic_profiles import build_pinned_execution_binding
from core.providers.agentic_adapter import RuntimeHealth
from core.providers.certificate_projection import certificate_profile_status
from core.providers.certificate_service import (
    _evidence_digest_is_valid, build_capability_evidence, publish_capability_certificate,
    validate_certificate_for_binding,
)
from core.providers.errors import CapabilityCertificateError
from core.providers.store import _capability_certificate
from core.runtime.authority_service import revalidate_runtime_authority_snapshot
from core.runtime.authority import resolve_effective_runtime_authority
from core.runtime.execution_binding import canonical_digest
from core.runtime.full_workspace_contract import FULL_WORKSPACE_CORE_TOOL_HANDLES
from tests.support.api_certificate_targets import api_certificate_fixture


NOW = datetime(2026, 9, 6, tzinfo=UTC)


class ApiCertificateTargetTest(TestCase):
    def cases(self):
        return tuple(
            api_certificate_fixture(provider_id, now=NOW)
            for provider_id in ("google-ai-studio", "openrouter")
        )

    def test_exact_target_with_narrowed_workspace_budget_survives_fast_refresh(self):
        for profile, adapter, binding, store in self.cases():
            binding = replace(binding, workspace_policy_ceiling_snapshot=replace(
                profile.policy_ceiling, max_steps_per_turn=2,
            ))
            with mock.patch("core.runtime.authority.feature_enabled", return_value=True), mock.patch(
                "core.runtime.authority_service.live_runtime_actor_policy", return_value=(True, "fixture-actor"),
            ):
                authority = resolve_effective_runtime_authority(
                    store, binding=binding, adapter=adapter, turn_id="target-turn", now=NOW,
                    currently_authorized_tool_handles=FULL_WORKSPACE_CORE_TOOL_HANDLES,
                    actor_policy_revision="fixture-actor",
                    health_revision=f"runtime-health:{canonical_digest(RuntimeHealth(status='healthy'))}",
                )
                self.assertEqual(revalidate_runtime_authority_snapshot(
                    SimpleNamespace(provider_store=store),
                    session=SimpleNamespace(execution_binding=binding, effective_mode="full-access"),
                    adapter=adapter, authority=authority, now=NOW,
                ), authority)

    def test_revision_policy_context_and_config_changes_cannot_inherit_certificate(self):
        for profile, adapter, binding, store in self.cases():
            certificate = store.get_capability_certificate(binding.capability_certificate_id)
            status = store.get_capability_certificate_status(certificate.certificate_id)
            variants = (
                replace(profile, revision=profile.revision + "-next"),
                replace(profile, policy_ceiling=replace(profile.policy_ceiling, max_steps_per_turn=999)),
                replace(profile, policy_ceiling=replace(profile.policy_ceiling, max_tool_calls_per_turn=999)),
                replace(profile, policy_ceiling=replace(profile.policy_ceiling, max_estimated_cost_microusd=999999)),
                replace(profile, context_policy=replace(profile.context_policy, context_reserve_tokens=1)),
                replace(profile, provider_config_digest="f" * 64),
                replace(profile, model_revision="uncertified-revision"),
                replace(profile, egress_policy_revision="uncertified"),
            )
            for candidate in variants:
                with self.subTest(candidate=candidate):
                    self.assertEqual(certificate_profile_status(
                        certificate, status, definition=candidate, adapter=adapter, now=NOW,
                    ), "certificate_target_mismatch")
            self.assertEqual(certificate_profile_status(
                certificate, status, definition=replace(profile, created_at=NOW + timedelta(days=1)),
                adapter=adapter, now=NOW,
            ), "active")

    def test_new_profile_revision_is_denied_at_admission(self):
        for profile, adapter, binding, store in self.cases():
            revised = replace(profile, revision=profile.revision + "-next")
            workspace = store.get_workspace_agentic_profile_binding(binding.workspace_binding_id)
            registry = SimpleNamespace(
                native_catalog_lock=RLock(),
                get_provider_definition=lambda provider_id: SimpleNamespace(provider_id=provider_id, requires_credentials=False),
                get_agentic_runtime_adapter=lambda provider_id: adapter,
            )
            with mock.patch("core.providers.agentic_profiles.feature_enabled", return_value=True), mock.patch(
                "core.providers.agentic_profiles.resolve_workspace_agentic_profile", return_value=(revised, workspace),
            ), self.assertRaisesRegex(CapabilityCertificateError, "certificate_target_mismatch"):
                build_pinned_execution_binding(
                    store, registry, session_id=binding.session_id, workspace_id="default",
                    execution_mode="full-access", now=NOW,
                )

    def test_full_validation_and_fast_refresh_recheck_target_and_pinned_limits(self):
        for profile, adapter, binding, store in self.cases():
            validate_certificate_for_binding(store, binding=binding, adapter=adapter, now=NOW)
            revised = replace(profile, revision=profile.revision + "-next")
            store.save_agentic_profile_definition(revised)
            variants = (
                (replace(binding, profile_definition_revision=revised.revision), "certificate_target_mismatch"),
                (replace(binding, profile_definition_revision="missing"), "certificate_target_profile_missing"),
                (replace(binding, profile_policy_ceiling_snapshot=replace(profile.policy_ceiling, max_steps_per_turn=999)),
                 "certificate_target_binding_mismatch"),
                (replace(binding, context_policy_snapshot=replace(profile.context_policy, context_reserve_tokens=1)),
                 "certificate_target_binding_mismatch"),
                (replace(binding, model_id="another-model"), "certificate_target_binding_mismatch"),
            )
            for pin, reason in variants:
                with self.subTest(reason=reason), self.assertRaisesRegex(CapabilityCertificateError, reason):
                    validate_certificate_for_binding(store, binding=pin, adapter=adapter, now=NOW)
                with self.subTest(refresh=reason), self.assertRaisesRegex(CapabilityCertificateError, reason):
                    revalidate_runtime_authority_snapshot(
                        SimpleNamespace(provider_store=store), session=SimpleNamespace(execution_binding=pin),
                        adapter=adapter, now=NOW, authority=SimpleNamespace(
                            execution_binding_id=pin.execution_binding_id, certificate_id=pin.capability_certificate_id,
                        ),
                    )

    def test_targetless_historical_api_certificate_fails_closed(self):
        for profile, adapter, binding, store in self.cases():
            document = asdict(store.get_capability_certificate(binding.capability_certificate_id))
            document.pop("certification_target_digest")
            historical = _capability_certificate(document)
            self.assertEqual(historical.certification_target_digest, "")
            self.assertEqual(certificate_profile_status(
                historical, store.get_capability_certificate_status(historical.certificate_id),
                definition=profile, adapter=adapter, now=NOW,
            ), "certificate_target_missing_or_invalid")
            with self.assertRaisesRegex(CapabilityCertificateError, "certificate_target_missing_or_invalid"):
                publish_capability_certificate(
                    store, certificate=historical, evidence=store.get_capability_evidence(historical.evidence_digest),
                )

    def test_target_is_bound_to_evidence_and_cannot_be_relabelled(self):
        for _, adapter, binding, store in self.cases():
            certificate = store.get_capability_certificate(binding.capability_certificate_id)
            evidence = store.get_capability_evidence(certificate.evidence_digest)
            self.assertTrue(_evidence_digest_is_valid(evidence))
            self.assertFalse(_evidence_digest_is_valid(replace(evidence, certification_target_digest="f" * 64)))
            self.assertFalse(_evidence_digest_is_valid(replace(evidence, certification_target_digest="")))
            with self.assertRaisesRegex(CapabilityCertificateError, "certificate_evidence_identity_mismatch"):
                publish_capability_certificate(store, certificate=replace(certificate, certification_target_digest="f" * 64), evidence=evidence)
            with mock.patch.object(store, "get_capability_certificate", return_value=replace(certificate, certification_target_digest="f" * 64)):
                with self.assertRaisesRegex(CapabilityCertificateError, "certificate_evidence_identity_mismatch"):
                    validate_certificate_for_binding(store, binding=binding, adapter=adapter, now=NOW)

    def test_native_evidence_hash_domain_is_unchanged(self):
        evidence = build_capability_evidence(
            suite_id="native-connection-fixture", suite_version="1", test_run_id="run-native",
            adapter_artifact_digest="a" * 64, result_summary_digest="b" * 64,
            evidence_refs=("platform-evidence:native",), recorded_at=NOW,
            source_commit="c" * 40, certification_outcome="passed",
        )
        old_payload = asdict(evidence)
        old_payload.pop("evidence_digest")
        old_payload.pop("certification_target_digest")
        self.assertEqual(evidence.evidence_digest, canonical_digest(old_payload))
        self.assertTrue(_evidence_digest_is_valid(evidence))
        self.assertFalse(_evidence_digest_is_valid(replace(evidence, certification_target_digest="d" * 64)))
