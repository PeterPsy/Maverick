from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import os
import unittest
from unittest.mock import patch

from core.api.platform_state import bootstrap_platform_state
from core.api.runtime_api import _list_session_payloads
from core.api.runtime_cleanup_batch import cleanup_runtime_sessions_batch
from core.cli.recovery_commands import recovery_command_specs
from core.providers.agentic_profiles import build_pinned_execution_binding
from core.providers.certificate_service import (
    build_capability_evidence,
    publish_capability_certificate,
)
from core.recovery.continuation_admission import assess_runtime_session_admission
from core.recovery.continuation_fork import (
    admit_runtime_session,
    repair_compatible_runtime_continuations,
)
from core.recovery.health_checks import run_runtime_health_check
from core.runtime.continuation_lineage import runtime_lineage_events
from core.runtime.execution_binding import (
    build_runtime_execution_binding,
    canonical_digest,
)
from core.runtime.service import create_runtime_session, transition_runtime_session
from core.runtime.errors import RuntimeProviderStateError, RuntimeSessionNotFoundError
from core.runtime.runtime_threads import create_runtime_thread
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


class RuntimeContinuationForkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_repo_root(self)
        with patch.dict(
            os.environ,
            {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"},
            clear=False,
        ):
            self.state = bootstrap_platform_state(
                start_path=self.root,
                now=NOW,
                install_builtin_apps=False,
            )

    def test_compatible_obsolete_binding_forks_without_mutating_history(self) -> None:
        source = self._source_session("source-session")
        original_binding = source.execution_binding

        assessment = assess_runtime_session_admission(
            self.state.provider_store,
            self.state.runtime_store,
            self.state.provider_registry,
            session=source,
            target_session_id="successor-preview",
            now=NOW,
        )
        self.assertEqual(assessment.status, "compatible_upgrade")
        self.assertEqual(assessment.detail_code, "adapter_artifact_mismatch")
        health = run_runtime_health_check(
            source,
            provider_store=self.state.provider_store,
            runtime_store=self.state.runtime_store,
            provider_registry=self.state.provider_registry,
            now=NOW,
        )
        self.assertEqual(health.status, "degraded")
        self.assertIn("adapter_artifact_mismatch", health.detail)

        result = admit_runtime_session(self.state, session=source, now=NOW)
        successor = result.session
        predecessor = self.state.runtime_store.get_session(source.session_id)

        self.assertEqual(result.status, "forked")
        self.assertEqual(predecessor.execution_binding, original_binding)
        self.assertEqual(predecessor.execution_binding.profile_definition_revision, "5")
        self.assertEqual(predecessor.status, "stopped")
        self.assertEqual(predecessor.continuation_successor_session_id, successor.session_id)
        self.assertEqual(successor.predecessor_session_id, predecessor.session_id)
        self.assertEqual(successor.execution_binding.profile_definition_revision, "8")
        self.assertEqual(result.handoff.phase, "completed")

        source_state = self.state.runtime_store.get_provider_state(predecessor.session_id)
        target_state = self.state.runtime_store.get_provider_state(successor.session_id)
        self.assertEqual(source_state.provider_thread_id, "provider-thread-source-session")
        self.assertEqual(target_state.provider_thread_id, source_state.provider_thread_id)
        self.assertEqual(target_state.continuation_id, source_state.continuation_id)
        self.assertEqual(source_state.continuation_handoff_id, result.handoff.handoff_id)
        self.assertEqual(
            source_state.continuation_successor_session_id,
            successor.session_id,
        )

        thread = self.state.runtime_store.get_thread(source.session_id)
        self.assertEqual(thread.thread_id, source.session_id)
        self.assertEqual(thread.runtime_session_id, successor.session_id)
        self.assertEqual(
            [event.event_type for event in runtime_lineage_events(self.state.runtime_store, successor)],
            ["runtime.continuation.forked", "runtime.continuation.accepted"],
        )

        second = admit_runtime_session(self.state, session=predecessor, now=NOW)
        self.assertEqual(second.status, "direct")
        self.assertEqual(second.session.session_id, successor.session_id)
        self.assertEqual(
            run_runtime_health_check(
                successor,
                provider_store=self.state.provider_store,
                runtime_store=self.state.runtime_store,
                provider_registry=self.state.provider_registry,
                now=NOW,
            ).status,
            "healthy",
        )
        self.assertEqual(len(self.state.runtime_store.list_all_sessions()), 2)
        self.assertEqual(
            [
                item["session_id"]
                for item in _list_session_payloads(
                    self.state,
                    workspace_id="default",
                    start_path=self.root,
                )
            ],
            [successor.session_id],
        )

    def test_interrupted_handoff_resumes_from_durable_phase(self) -> None:
        source = self._source_session("source-interrupted")
        original_rebind = self.state.runtime_store.rebind_runtime_thread_session
        calls = 0

        def fail_once(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("simulated crash before thread rebind")
            return original_rebind(**kwargs)

        with patch.object(
            self.state.runtime_store,
            "rebind_runtime_thread_session",
            side_effect=fail_once,
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated crash"):
                admit_runtime_session(self.state, session=source, now=NOW)

        predecessor = self.state.runtime_store.get_session(source.session_id)
        handoff = self.state.runtime_store.get_continuation_handoff_by_predecessor(
            workspace_id="default",
            predecessor_session_id=source.session_id,
        )
        self.assertEqual(handoff.phase, "predecessor_fenced")
        self.assertIsNotNone(predecessor.continuation_successor_session_id)
        with self.assertRaisesRegex(
            RuntimeProviderStateError,
            "phase must advance exactly once",
        ):
            self.state.runtime_store.update_continuation_handoff(
                replace(
                    handoff,
                    phase="completed",
                    revision=handoff.revision + 1,
                ),
                expected_revision=handoff.revision,
            )

        resumed = admit_runtime_session(self.state, session=predecessor, now=NOW)

        self.assertEqual(resumed.status, "forked")
        self.assertEqual(resumed.handoff.phase, "completed")
        self.assertEqual(
            self.state.runtime_store.get_thread(source.session_id).runtime_session_id,
            resumed.session.session_id,
        )

    def test_repair_dry_run_classifies_without_writing_runtime_state(self) -> None:
        source = self._source_session("source-dry-run")
        provider_state_before = self.state.runtime_store.get_provider_state(
            source.session_id
        )

        result = repair_compatible_runtime_continuations(
            self.state,
            workspace_id="default",
            session_ids={source.session_id},
            dry_run=True,
            now=NOW,
        )

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["inspected_count"], 1)
        self.assertEqual(result["compatible_count"], 1)
        self.assertEqual(result["inventory"][0]["status"], "compatible_upgrade")
        self.assertEqual(self.state.runtime_store.list_all_sessions(), [source])
        self.assertIsNone(
            self.state.runtime_store.get_continuation_handoff_by_predecessor(
                workspace_id="default",
                predecessor_session_id=source.session_id,
            )
        )
        self.assertEqual(
            self.state.runtime_store.get_provider_state(source.session_id),
            provider_state_before,
        )

    def test_bulk_repair_surface_is_admin_only_and_has_a_bounded_schema(self) -> None:
        definition, _handler = next(
            item
            for item in recovery_command_specs()
            if item[0].command_id == "core.recovery.repair_continuations"
        )

        self.assertEqual(definition.invocation_policy.required_platform_role, "admin")
        self.assertTrue(definition.invocation_policy.requires_full_access)
        self.assertFalse(definition.argument_schema["additionalProperties"])
        self.assertEqual(
            definition.argument_schema["properties"]["session_ids"]["maxItems"],
            500,
        )

    def test_upgrade_rejects_unproven_or_expanding_authority_changes(self) -> None:
        scenarios = (
            (
                "model",
                {"source_model_id": "different-model"},
                "runtime_profile_upgrade_incompatible_model_id",
            ),
            (
                "routing",
                {"routing_mismatch": True},
                "runtime_profile_upgrade_incompatible_routing_constraint_snapshot",
            ),
            (
                "egress",
                {"egress_mismatch": True},
                "runtime_profile_upgrade_incompatible_egress_policy_id",
            ),
            (
                "policy",
                {"policy_mismatch": True},
                "runtime_profile_upgrade_incompatible_workspace_policy_ceiling_snapshot",
            ),
            (
                "capability",
                {"restrict_source_capability": True},
                "runtime_profile_upgrade_capability_expansion",
            ),
            (
                "legacy",
                {"legacy_inferred": True},
                "runtime_profile_upgrade_legacy_authority_unproven",
            ),
        )
        for label, kwargs, expected_detail in scenarios:
            with self.subTest(label=label):
                source = self._source_session(f"source-negative-{label}", **kwargs)
                assessment = assess_runtime_session_admission(
                    self.state.provider_store,
                    self.state.runtime_store,
                    self.state.provider_registry,
                    session=source,
                    target_session_id=f"target-negative-{label}",
                    now=NOW,
                )
                self.assertEqual(assessment.status, "upgrade_required")
                self.assertEqual(assessment.detail_code, expected_detail)

    def test_upgrade_rejects_revoked_source_certificate(self) -> None:
        source = self._source_session("source-revoked")
        certificate_id = source.execution_binding.capability_certificate_id
        status = self.state.provider_store.get_capability_certificate_status(certificate_id)
        self.state.provider_store.save_capability_certificate_status(
            replace(
                status,
                status="revoked",
                revision=status.revision + 1,
                updated_at=NOW,
                revoked_at=NOW,
                revocation_reason="test revocation",
            ),
            expected_revision=status.revision,
        )

        assessment = assess_runtime_session_admission(
            self.state.provider_store,
            self.state.runtime_store,
            self.state.provider_registry,
            session=source,
            target_session_id="target-revoked",
            now=NOW,
        )

        self.assertEqual(assessment.status, "upgrade_required")
        self.assertEqual(assessment.detail_code, "certificate_revoked")

    def test_upgrade_reports_missing_provider_thread_without_creating_one(self) -> None:
        source = self._source_session("source-provider-thread-missing")
        provider_state = self.state.runtime_store.get_provider_state(source.session_id)
        self.state.runtime_store.update_provider_state(
            replace(
                provider_state,
                provider_thread_id=None,
                continuation_id=None,
                revision=provider_state.revision + 1,
                updated_at=NOW,
            ),
            expected_revision=provider_state.revision,
        )

        assessment = assess_runtime_session_admission(
            self.state.provider_store,
            self.state.runtime_store,
            self.state.provider_registry,
            session=source,
            target_session_id="target-provider-thread-missing",
            now=NOW,
        )

        self.assertEqual(assessment.status, "provider_thread_missing")
        self.assertEqual(assessment.detail_code, "provider_thread_missing")

    def test_upgrade_rejects_provider_state_that_is_still_in_flight(self) -> None:
        source = self._source_session("source-provider-state-busy")
        provider_state = self.state.runtime_store.get_provider_state(source.session_id)
        self.state.runtime_store.update_provider_state(
            replace(
                provider_state,
                provider_request_id="request-in-flight",
                turn_generation="generation-in-flight",
                revision=provider_state.revision + 1,
                updated_at=NOW,
            ),
            expected_revision=provider_state.revision,
        )

        assessment = assess_runtime_session_admission(
            self.state.provider_store,
            self.state.runtime_store,
            self.state.provider_registry,
            session=source,
            target_session_id="target-provider-state-busy",
            now=NOW,
        )

        self.assertEqual(assessment.status, "upgrade_required")
        self.assertEqual(
            assessment.detail_code,
            "runtime_profile_upgrade_provider_state_busy",
        )

    def test_cleanup_of_current_session_removes_complete_continuation_lineage(self) -> None:
        source = self._source_session("source-cleanup-lineage")
        result = admit_runtime_session(self.state, session=source, now=NOW)
        handoff_id = result.handoff.handoff_id

        cleanup = cleanup_runtime_sessions_batch(
            self.state,
            session_ids=[source.session_id],
            workspace_id="default",
            reason="test cleanup",
            start_path=self.root,
        )

        self.assertEqual(
            set(cleanup["expanded_session_ids"]),
            {source.session_id, result.session.session_id},
        )
        for session_id in (source.session_id, result.session.session_id):
            with self.assertRaises(RuntimeSessionNotFoundError):
                self.state.runtime_store.get_session(session_id)
        with self.assertRaises(RuntimeProviderStateError):
            self.state.runtime_store.get_continuation_handoff(handoff_id)

    def test_non_chat_session_kind_is_not_automatically_forked(self) -> None:
        source = self._source_session(
            "source-inter-agent-participant",
            session_kind="inter_agent_participant",
        )

        assessment = assess_runtime_session_admission(
            self.state.provider_store,
            self.state.runtime_store,
            self.state.provider_registry,
            session=source,
            target_session_id="target-inter-agent-participant",
            now=NOW,
        )

        self.assertEqual(assessment.status, "upgrade_required")
        self.assertEqual(
            assessment.detail_code,
            "runtime_profile_upgrade_session_kind_unsupported",
        )

    def _source_session(
        self,
        session_id: str,
        *,
        source_model_id: str | None = None,
        routing_mismatch: bool = False,
        egress_mismatch: bool = False,
        policy_mismatch: bool = False,
        restrict_source_capability: bool = False,
        legacy_inferred: bool = False,
        session_kind: str = "chat_root",
    ):
        target = build_pinned_execution_binding(
            self.state.provider_store,
            self.state.provider_registry,
            session_id=f"{session_id}-target-template",
            workspace_id="default",
            execution_mode="full-access",
            now=NOW,
        )
        target_certificate = self.state.provider_store.get_capability_certificate(
            target.capability_certificate_id
        )
        old_artifact_digest = "2" * 64
        old_evidence = build_capability_evidence(
            suite_id=target_certificate.suite_id,
            suite_version=target_certificate.suite_version,
            test_run_id=f"old-revision:{session_id}",
            adapter_artifact_digest=old_artifact_digest,
            result_summary_digest=canonical_digest({"session_id": session_id}),
            evidence_refs=target_certificate.evidence_refs,
            recorded_at=NOW,
        )
        source_routing = (
            replace(
                target.routing_constraint_snapshot,
                allowed_upstream_ids=("incompatible-upstream",),
            )
            if routing_mismatch
            else target.routing_constraint_snapshot
        )
        source_capabilities = target_certificate.certified_capabilities
        if restrict_source_capability:
            source_capabilities = replace(source_capabilities, shell=False)
        old_certificate = replace(
            target_certificate,
            certificate_id=f"old-certificate:{session_id}",
            adapter_artifact_digest=old_artifact_digest,
            test_run_id=old_evidence.test_run_id,
            evidence_digest=old_evidence.evidence_digest,
            model_id=source_model_id or target.model_id,
            certified_upstream_ids=source_routing.allowed_upstream_ids,
            routing_constraint_digest=canonical_digest(source_routing),
            certified_capabilities=source_capabilities,
            issued_at=NOW,
        )
        publish_capability_certificate(
            self.state.provider_store,
            certificate=old_certificate,
            evidence=old_evidence,
        )
        source_binding = build_runtime_execution_binding(
            session_id=session_id,
            workspace_id="default",
            profile_definition_id=target.profile_definition_id,
            profile_definition_revision="5",
            workspace_binding_id=target.workspace_binding_id,
            workspace_binding_revision=target.workspace_binding_revision,
            capability_certificate_id=old_certificate.certificate_id,
            runtime_engine_id=target.runtime_engine_id,
            adapter_id=target.adapter_id,
            adapter_version=target.adapter_version,
            adapter_artifact_digest=old_artifact_digest,
            model_provider_id=target.model_provider_id,
            model_id=source_model_id or target.model_id,
            provider_protocol=target.provider_protocol,
            provider_api_version=target.provider_api_version,
            routing_constraint=source_routing,
            credential_binding_id=target.credential_binding_id,
            reasoning_effort=target.reasoning_effort,
            certified_reasoning_efforts=target.certified_reasoning_efforts,
            default_reasoning_effort=target.default_reasoning_effort,
            execution_mode=target.execution_mode,
            profile_policy_ceiling=target.profile_policy_ceiling_snapshot,
            workspace_policy_ceiling=(
                replace(
                    target.workspace_policy_ceiling_snapshot,
                    max_steps_per_turn=max(
                        1,
                        target.workspace_policy_ceiling_snapshot.max_steps_per_turn - 1,
                    ),
                )
                if policy_mismatch
                else target.workspace_policy_ceiling_snapshot
            ),
            egress_policy_id=(
                "incompatible-egress-policy" if egress_mismatch else target.egress_policy_id
            ),
            egress_policy_revision=target.egress_policy_revision,
            certificate_evidence_digest=old_certificate.evidence_digest,
            created_at=NOW,
            legacy_inferred=legacy_inferred,
        )
        source = create_runtime_session(
            self.state.runtime_store,
            session_id=session_id,
            workspace_id="default",
            agent_id="chat",
            source_app_id="chat",
            thread_title="Continuation test",
            agent_label="Codex",
            session_kind=session_kind,
            runtime_mode="agentic",
            requested_mode="full-access",
            governance=self.state.workspace_store.get_governance("default"),
            platform_allows_full_access=True,
            start_path=self.root,
            execution_binding=source_binding,
            now=NOW,
        )
        source = transition_runtime_session(
            self.state.runtime_store,
            session_id=session_id,
            target_status="running",
            now=NOW,
        )
        provider_state = self.state.runtime_store.get_provider_state(session_id)
        self.state.runtime_store.update_provider_state(
            replace(
                provider_state,
                provider_thread_id=f"provider-thread-{session_id}",
                continuation_id=f"continuation-{session_id}",
                revision=provider_state.revision + 1,
                updated_at=NOW,
            ),
            expected_revision=provider_state.revision,
        )
        if session_kind == "chat_root":
            create_runtime_thread(
                self.state.runtime_store,
                workspace_id="default",
                thread_id=session_id,
                runtime_session_id=session_id,
                title="Continuation test",
                agent_label="Codex",
                source_app_id="chat",
                system_prompt="",
                now=NOW,
            )
        return self.state.runtime_store.get_session(session_id)


if __name__ == "__main__":
    unittest.main()
