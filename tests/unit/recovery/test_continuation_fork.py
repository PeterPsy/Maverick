from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

from core.api.runtime_api import _list_session_payloads
from core.providers.agentic_profiles import CODEX_PROFILE_REVISION
from core.recovery.continuation_admission import assess_runtime_session_admission
from core.recovery.continuation_fork import admit_runtime_session
from core.recovery.health_checks import run_runtime_health_check
from core.runtime.continuation_lineage import runtime_lineage_events
from core.runtime.errors import (
    RuntimeProviderStateError,
    RuntimeSessionNotFoundError,
    RuntimeTransitionError,
)
from core.runtime.errors import RuntimeProfileUpgradeRequiredError
from core.runtime.lifecycle import queue_runtime_turn
from tests.support.continuation import NOW, RuntimeContinuationFixture


class RuntimeContinuationForkTest(RuntimeContinuationFixture, unittest.TestCase):
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
        self.assertEqual(
            successor.execution_binding.profile_definition_revision,
            CODEX_PROFILE_REVISION,
        )
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
        with self.assertRaises(RuntimeTransitionError):
            queue_runtime_turn(
                self.state.runtime_store,
                turn_id="stale-predecessor-turn",
                session_id=predecessor.session_id,
                input_text="must use the current lineage tip",
                now=NOW,
            )
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

    def test_planned_handoff_resumes_before_successor_exists(self) -> None:
        source = self._source_session("source-planned-handoff")
        with patch(
            "core.recovery.continuation_handoff_service.ensure_successor_session",
            side_effect=RuntimeError("simulated crash before successor creation"),
        ):
            with self.assertRaisesRegex(RuntimeError, "before successor creation"):
                admit_runtime_session(self.state, session=source, now=NOW)

        handoff = self.state.runtime_store.get_continuation_handoff_by_predecessor(
            workspace_id="default",
            predecessor_session_id=source.session_id,
        )
        self.assertEqual(handoff.phase, "planned")
        with self.assertRaises(RuntimeSessionNotFoundError):
            self.state.runtime_store.get_session(handoff.successor_session_id)
        with self.assertRaises(RuntimeTransitionError):
            queue_runtime_turn(
                self.state.runtime_store,
                turn_id="planned-handoff-stale-turn",
                session_id=source.session_id,
                input_text="must wait for the pending handoff",
                now=NOW,
            )

        from core.recovery import continuation_fork
        original_handoff_lookup = continuation_fork._continuation_handoff_for_session
        lookups = 0

        def hide_handoff_before_lock(state, session):
            nonlocal lookups
            lookups += 1
            if lookups == 1:
                return None
            return original_handoff_lookup(state, session)

        with patch.object(
            continuation_fork,
            "_continuation_handoff_for_session",
            side_effect=hide_handoff_before_lock,
        ):
            resumed = admit_runtime_session(self.state, session=source, now=NOW)

        self.assertEqual(resumed.status, "forked")
        self.assertEqual(resumed.handoff.phase, "completed")
        self.assertGreaterEqual(lookups, 3)

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
                "egress_policy_drift_unresolved",
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

    def test_upgrade_rejects_queued_turn_before_forking(self) -> None:
        source = self._source_session("source-queued-turn")
        queue_runtime_turn(
            self.state.runtime_store,
            turn_id="turn-before-continuation",
            session_id=source.session_id,
            input_text="preserve me",
            now=NOW,
        )

        with self.assertRaises(RuntimeProfileUpgradeRequiredError) as caught:
            admit_runtime_session(self.state, session=source, now=NOW)

        self.assertEqual(caught.exception.detail_code, "runtime_profile_upgrade_turn_busy")
        self.assertEqual(
            self.state.runtime_store.get_session(source.session_id).status,
            "running",
        )
        self.assertEqual(
            self.state.runtime_store.get_turn("turn-before-continuation").status,
            "queued",
        )
        self.assertEqual(len(self.state.runtime_store.list_all_sessions()), 1)

    def test_upgrade_requires_predecessor_process_to_be_closed(self) -> None:
        source = self._source_session("source-live-process")

        with patch(
            "core.recovery.continuation_materialization.runtime_processes_alive_for_session",
            return_value=True,
        ):
            with self.assertRaisesRegex(
                RuntimeProviderStateError,
                "runtime_continuation_predecessor_process_still_running",
            ):
                admit_runtime_session(self.state, session=source, now=NOW)

        predecessor = self.state.runtime_store.get_session(source.session_id)
        handoff = self.state.runtime_store.get_continuation_handoff_by_predecessor(
            workspace_id="default",
            predecessor_session_id=source.session_id,
        )
        self.assertEqual(predecessor.status, "running")
        self.assertEqual(handoff.phase, "successor_prepared")
        self.assertIsNone(predecessor.continuation_successor_session_id)
        self.assertIsNone(
            self.state.runtime_store.get_provider_state(source.session_id).continuation_handoff_id
        )

    def test_interrupted_handoff_rejects_revoked_target_certificate(self) -> None:
        source = self._source_session("source-revoked-target")
        with patch.object(
            self.state.runtime_store,
            "rebind_runtime_thread_session",
            side_effect=RuntimeError("simulated crash before thread rebind"),
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated crash"):
                admit_runtime_session(self.state, session=source, now=NOW)
        handoff = self.state.runtime_store.get_continuation_handoff_by_predecessor(
            workspace_id="default",
            predecessor_session_id=source.session_id,
        )
        certificate_id = handoff.target_execution_binding.capability_certificate_id
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

        with self.assertRaises(RuntimeProfileUpgradeRequiredError) as caught:
            admit_runtime_session(
                self.state,
                session=self.state.runtime_store.get_session(source.session_id),
                now=NOW,
            )

        self.assertEqual(
            caught.exception.detail_code,
            "runtime_continuation_certificate_revoked",
        )
        self.assertEqual(
            self.state.runtime_store.get_session(handoff.successor_session_id).status,
            "stopped",
        )
        self.assertNotEqual(
            self.state.runtime_store.get_continuation_handoff(handoff.handoff_id).phase,
            "completed",
        )

    def test_interrupted_handoff_rejects_disabled_live_workspace_binding(self) -> None:
        source = self._source_session("source-disabled-target-binding")
        with patch.object(
            self.state.runtime_store,
            "rebind_runtime_thread_session",
            side_effect=RuntimeError("simulated crash before thread rebind"),
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated crash"):
                admit_runtime_session(self.state, session=source, now=NOW)
        handoff = self.state.runtime_store.get_continuation_handoff_by_predecessor(
            workspace_id="default",
            predecessor_session_id=source.session_id,
        )
        binding = self.state.provider_store.get_workspace_agentic_profile_binding(
            handoff.target_execution_binding.workspace_binding_id
        )
        self.state.provider_store.save_workspace_agentic_profile_binding(
            replace(
                binding,
                enabled=False,
                is_default=False,
                revision=binding.revision + 1,
                updated_at=NOW,
            ),
            expected_revision=binding.revision,
        )

        with self.assertRaises(RuntimeProfileUpgradeRequiredError) as caught:
            admit_runtime_session(self.state, session=source, now=NOW)

        self.assertEqual(
            caught.exception.detail_code,
            "runtime_continuation_workspace_profile_binding_disabled",
        )
        self.assertEqual(
            self.state.runtime_store.get_session(handoff.successor_session_id).status,
            "stopped",
        )

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

if __name__ == "__main__":
    unittest.main()
