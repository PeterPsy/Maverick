"""Remote-agentic containment partial-apply and CLI retry contracts."""

from __future__ import annotations

from datetime import timedelta
import unittest
from unittest.mock import patch

from core.cli.models import CliInvocationContext
from core.cli.runtime_provider_commands import runtime_provider_command_specs
from core.observability.store import ObservabilityCollections, ObservabilityDocumentStore
from core.providers.agentic_containment import (
    RemoteAgenticContainmentApplyError,
    run_remote_agentic_containment,
)
from core.providers.errors import AgenticProfileConflictError
from core.runtime.errors import RuntimeTransitionError
from tests.support.collections import FakeCollection
from tests.support.remote_agentic_containment_fixture import (
    NOW,
    RemoteAgenticContainmentFixture,
)


class RemoteAgenticContainmentApplyTest(RemoteAgenticContainmentFixture, unittest.TestCase):
    def test_partial_apply_failure_is_audited_and_requires_new_review(self) -> None:
        audit_collection = FakeCollection()
        observability_store = ObservabilityDocumentStore(
            ObservabilityCollections(
                events=FakeCollection(),
                audit=audit_collection,
                metrics=FakeCollection(),
            )
        )
        reviewed = run_remote_agentic_containment(
            self.provider_store,
            self.runtime_store,
            mode="dry_run",
            now=NOW,
        )

        with patch.object(
            self.provider_store,
            "save_agentic_profile_definition_status",
            side_effect=AgenticProfileConflictError("profile_status_revision_conflict"),
        ), self.assertRaises(RemoteAgenticContainmentApplyError) as raised:
            run_remote_agentic_containment(
                self.provider_store,
                self.runtime_store,
                mode="apply",
                expected_plan_digest=reviewed.plan_digest,
                now=NOW + timedelta(minutes=1),
                observability_store=observability_store,
            )

        binding = self.provider_store.get_workspace_agentic_profile_binding(
            self.remote_binding.binding_id
        )
        profile_status = self.provider_store.get_agentic_profile_definition_status(
            self.remote_definition.definition_id,
            self.remote_definition.revision,
        )
        certificate_status = self.provider_store.get_capability_certificate_status(
            self.remote_certificate.certificate_id
        )
        session = self.runtime_store.get_session(self.remote_session.session_id)
        self.assertFalse(binding.enabled)
        self.assertEqual(profile_status.rollout_status, "preview")
        self.assertEqual(certificate_status.status, "active")
        self.assertEqual(session.status, "running")
        self.assertEqual(
            raised.exception.reason_code,
            "remote_agentic_containment_apply_failed_new_review_required",
        )
        self.assertFalse(raised.exception.safe_to_retry)
        self.assertTrue(raised.exception.requires_new_dry_run)
        audits = observability_store.list_audit(source_domain="providers")
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertEqual(audit.status, "failed")
        self.assertEqual(audit.action, "provider.remote_agentic_containment.apply")
        self.assertEqual(
            audit.payload,
            {
                "plan_digest": reviewed.plan_digest,
                "bindings_disabled": 1,
                "profiles_suspended": 0,
                "certificates_revoked": 0,
                "sessions_quarantined": 0,
                "partial_apply": True,
                "safe_to_retry": False,
                "requires_new_dry_run": True,
                "requires_post_apply_verification": False,
                "failure_code": "provider_record_cas_conflict",
                "failure_stage": "profile",
                "failed_target_digest": reviewed.profile_targets[0].target_digest,
            },
        )

    def test_operator_cli_dry_run_is_read_only_and_apply_requires_review_token(self) -> None:
        commands = {
            definition.command_id: (definition, handler)
            for definition, handler in runtime_provider_command_specs(
                provider_store=self.provider_store,
                runtime_store=self.runtime_store,
            )
        }
        context = CliInvocationContext(
            caller_kind="operator",
            workspace_id="default",
            agent_id=None,
            effective_mode="full-access",
        )
        before = self._state_snapshot()
        definition, dry_run = commands["core.providers.agentic.containment.dry-run"]
        dry_result = dry_run({}, context)
        apply_definition, apply = commands["core.providers.agentic.containment.apply"]
        refused = apply(
            {"confirmation": "not-reviewed", "plan_digest": dry_result["report"]["plan_digest"]},
            context,
        )
        stale = apply(
            {"confirmation": "phase-0-reviewed", "plan_digest": "0" * 64},
            context,
        )

        self.assertTrue(definition.invocation_policy.operator_only)
        self.assertEqual(definition.effect_class, "read")
        self.assertFalse(apply_definition.supports_idempotency)
        self.assertFalse(apply_definition.safe_to_retry)
        self.assertEqual(dry_result["report"]["operational_status"], "live_apply_pending_review")
        self.assertEqual(refused["error"], "containment_apply_confirmation_required")
        self.assertFalse(refused["safe_to_retry"])
        self.assertTrue(refused["requires_new_dry_run"])
        self.assertEqual(stale["error"], "remote_agentic_containment_plan_changed")
        self.assertFalse(stale["safe_to_retry"])
        self.assertTrue(stale["requires_new_dry_run"])
        self.assertEqual(self._state_snapshot(), before)

    def test_session_lifecycle_conflict_never_records_containment_success(self) -> None:
        observability_store = ObservabilityDocumentStore(
            ObservabilityCollections(
                events=FakeCollection(),
                audit=FakeCollection(),
                metrics=FakeCollection(),
            )
        )
        reviewed = run_remote_agentic_containment(
            self.provider_store,
            self.runtime_store,
            mode="dry_run",
            now=NOW,
        )

        with patch(
            "core.providers.agentic_containment.transition_runtime_session",
            side_effect=RuntimeTransitionError("simulated lifecycle conflict"),
        ), self.assertRaises(RemoteAgenticContainmentApplyError) as raised:
            run_remote_agentic_containment(
                self.provider_store,
                self.runtime_store,
                mode="apply",
                expected_plan_digest=reviewed.plan_digest,
                now=NOW + timedelta(minutes=1),
                observability_store=observability_store,
            )

        self.assertEqual(
            raised.exception.reason_code,
            "remote_agentic_containment_apply_failed_new_review_required",
        )
        containment_audits = [
            audit
            for audit in observability_store.list_audit(source_domain="providers")
            if audit.action == "provider.remote_agentic_containment.apply"
        ]
        self.assertEqual(len(containment_audits), 1)
        audit = containment_audits[0]
        self.assertEqual(audit.status, "failed")
        self.assertEqual(audit.payload["failure_code"], "session_lifecycle_conflict")
        self.assertEqual(audit.payload["failure_stage"], "session")
        self.assertEqual(
            audit.payload["failed_target_digest"],
            reviewed.session_targets[0].target_digest,
        )
        self.assertEqual(audit.payload["bindings_disabled"], 1)
        self.assertEqual(audit.payload["profiles_suspended"], 1)
        self.assertEqual(audit.payload["certificates_revoked"], 1)
        self.assertEqual(audit.payload["sessions_quarantined"], 0)
        self.assertTrue(audit.payload["partial_apply"])
        self.assertFalse(audit.payload["safe_to_retry"])
        self.assertTrue(audit.payload["requires_new_dry_run"])


if __name__ == "__main__":
    unittest.main()
