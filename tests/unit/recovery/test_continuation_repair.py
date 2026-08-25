from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import unittest
from unittest.mock import patch

from core.api.runtime_cleanup_batch import cleanup_runtime_sessions_batch
from core.cli.recovery_commands import recovery_command_specs
from core.providers.agentic_models import (
    WorkspaceAgenticProfileBinding,
    default_actor_selection_policy,
)
from core.providers.agentic_profiles import publish_codex_agentic_profile
from core.providers.builtin_certification import ensure_codex_preview_certificate
from core.recovery import continuation_handoff_service
from core.recovery.continuation_admission import assess_runtime_session_admission
from core.recovery.continuation_fork import (
    admit_runtime_session,
    continuation_repair_inventory,
    repair_compatible_runtime_continuations,
)
from core.runtime.errors import (
    RuntimeProfileUpgradeRequiredError,
    RuntimeProviderStateError,
    RuntimeSessionNotFoundError,
    RuntimeTurnQueueRejectedError,
)
from core.runtime.provider_start_handoff import runtime_provider_start_handoff
from tests.support.continuation import NOW, RuntimeContinuationFixture


class RuntimeContinuationRepairTest(RuntimeContinuationFixture, unittest.TestCase):
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

    def test_upgrade_targets_current_binding_for_the_source_model(self) -> None:
        provider = self.state.provider_registry.get_provider_definition("codex")
        profile = publish_codex_agentic_profile(
            self.state.provider_store,
            definition=provider,
            model_id="alternate-certified-model",
            now=NOW,
        )
        ensure_codex_preview_certificate(
            self.state.provider_store,
            definition=profile,
            provider_definition=provider,
            adapter=self.state.provider_registry.get_agentic_runtime_adapter("codex"),
        )
        binding = WorkspaceAgenticProfileBinding(
            binding_id="alternate-current-binding",
            workspace_id="default",
            definition_id=profile.definition_id,
            definition_revision=profile.revision,
            credential_binding_id=None,
            enabled=True,
            is_default=False,
            actor_policy=default_actor_selection_policy(),
            workspace_policy_ceiling=profile.policy_ceiling,
            egress_policy_id=profile.egress_policy_id,
            egress_policy_revision=profile.egress_policy_revision,
            revision=0,
            created_at=NOW,
            updated_at=NOW,
        )
        self.state.provider_store.save_workspace_agentic_profile_binding(
            binding,
            expected_revision=None,
        )
        self.state.provider_store.save_workspace_agentic_profile_binding(
            replace(
                binding,
                binding_id="alternate-incompatible-newer-binding",
                workspace_policy_ceiling=replace(
                    binding.workspace_policy_ceiling,
                    max_steps_per_turn=max(
                        1,
                        binding.workspace_policy_ceiling.max_steps_per_turn - 1,
                    ),
                ),
                revision=99,
            ),
            expected_revision=None,
        )
        source = self._source_session(
            "source-alternate-model",
            target_workspace_binding_id=binding.binding_id,
        )

        assessment = assess_runtime_session_admission(
            self.state.provider_store,
            self.state.runtime_store,
            self.state.provider_registry,
            session=source,
            target_session_id="target-alternate-model",
            now=NOW,
        )

        self.assertEqual(assessment.status, "compatible_upgrade")
        self.assertEqual(
            assessment.target_execution_binding.model_id,
            "alternate-certified-model",
        )
        self.assertEqual(
            assessment.target_execution_binding.workspace_binding_id,
            binding.binding_id,
        )

    def test_invalid_planned_handoff_without_successor_preserves_authority_error(
        self,
    ) -> None:
        source = self._source_session("source-planned-revoked")
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
        status = self.state.provider_store.get_capability_certificate_status(
            source.execution_binding.capability_certificate_id
        )
        self.state.provider_store.save_capability_certificate_status(
            replace(
                status,
                status="revoked",
                revision=status.revision + 1,
                updated_at=NOW,
                revoked_at=NOW,
                revocation_reason="test planned handoff revocation",
            ),
            expected_revision=status.revision,
        )

        with self.assertRaises(RuntimeProfileUpgradeRequiredError) as caught:
            admit_runtime_session(self.state, session=source, now=NOW)

        self.assertEqual(
            caught.exception.detail_code,
            "runtime_continuation_certificate_revoked",
        )
        with self.assertRaises(RuntimeSessionNotFoundError):
            self.state.runtime_store.get_session(handoff.successor_session_id)

    def test_handoff_revalidates_authority_after_predecessor_process_close(self) -> None:
        source = self._source_session("source-mid-phase-governance-change")
        original_close = continuation_handoff_service.close_predecessor_runtime_process

        def close_then_disable_target(state, handoff):
            original_close(state, handoff)
            binding = state.provider_store.get_workspace_agentic_profile_binding(
                handoff.target_execution_binding.workspace_binding_id
            )
            state.provider_store.save_workspace_agentic_profile_binding(
                replace(
                    binding,
                    enabled=False,
                    is_default=False,
                    revision=binding.revision + 1,
                    updated_at=NOW,
                ),
                expected_revision=binding.revision,
            )

        with patch.object(
            continuation_handoff_service,
            "close_predecessor_runtime_process",
            side_effect=close_then_disable_target,
        ):
            with self.assertRaises(RuntimeProfileUpgradeRequiredError) as caught:
                admit_runtime_session(self.state, session=source, now=NOW)

        self.assertEqual(
            caught.exception.detail_code,
            "runtime_continuation_workspace_profile_binding_disabled",
        )
        handoff = self.state.runtime_store.get_continuation_handoff_by_predecessor(
            workspace_id="default",
            predecessor_session_id=source.session_id,
        )
        self.assertEqual(handoff.phase, "successor_prepared")
        self.assertIsNone(
            self.state.runtime_store.get_provider_state(
                source.session_id
            ).continuation_handoff_id
        )
        self.assertEqual(
            self.state.runtime_store.get_session(
                handoff.successor_session_id
            ).status,
            "stopped",
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

    def test_repair_inventory_resolves_each_lineage_to_its_current_tip(self) -> None:
        source = self._source_session("source-inventory-lineage")
        successor = admit_runtime_session(self.state, session=source, now=NOW).session

        inventory = continuation_repair_inventory(
            self.state,
            workspace_id="default",
            session_ids={source.session_id},
            now=NOW,
        )

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["session_id"], successor.session_id)
        self.assertEqual(
            inventory[0]["lineage_root_session_id"],
            source.session_id,
        )
        self.assertEqual(inventory[0]["status"], "direct")

    def test_repair_inventory_includes_an_interrupted_handoff(self) -> None:
        source = self._source_session("source-inventory-pending")
        with patch(
            "core.recovery.continuation_handoff_service.ensure_successor_session",
            side_effect=RuntimeError("simulated pending handoff"),
        ):
            with self.assertRaisesRegex(RuntimeError, "pending handoff"):
                admit_runtime_session(self.state, session=source, now=NOW)

        inventory = continuation_repair_inventory(
            self.state,
            workspace_id="default",
            session_ids={source.session_id},
            now=NOW,
        )

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["status"], "compatible_upgrade")
        self.assertEqual(
            inventory[0]["detail_code"],
            "runtime_continuation_handoff_pending",
        )

    def test_pending_handoff_blocks_stale_provider_prewarm_start(self) -> None:
        source = self._source_session("source-pending-provider-start")
        with patch(
            "core.recovery.continuation_handoff_service.ensure_successor_session",
            side_effect=RuntimeError("simulated pending provider start"),
        ):
            with self.assertRaisesRegex(RuntimeError, "pending provider start"):
                admit_runtime_session(self.state, session=source, now=NOW)

        with self.assertRaises(RuntimeTurnQueueRejectedError):
            with runtime_provider_start_handoff(
                self.state.runtime_store,
                session_id=source.session_id,
            ):
                self.fail("superseded provider start was admitted")

    def test_interrupted_handoff_rejects_changed_compatibility_reason(self) -> None:
        source = self._source_session("source-proof-reason-change")
        with patch(
            "core.recovery.continuation_handoff_service.ensure_successor_session",
            side_effect=RuntimeError("simulated pending proof"),
        ):
            with self.assertRaisesRegex(RuntimeError, "pending proof"):
                admit_runtime_session(self.state, session=source, now=NOW)

        with self.assertRaises(RuntimeProfileUpgradeRequiredError) as caught:
            admit_runtime_session(
                self.state,
                session=source,
                now=NOW + timedelta(days=400),
            )

        self.assertEqual(
            caught.exception.detail_code,
            "runtime_continuation_compatibility_proof_changed",
        )


if __name__ == "__main__":
    unittest.main()
