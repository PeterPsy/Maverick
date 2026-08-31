"""Remote-agentic containment inventory and successful-apply contracts."""

from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
from types import SimpleNamespace
import unittest

from core.api.provider_api import runtime_session_payload, workspace_agentic_admin_status
from core.api.runtime_api import _session_payload
from core.providers.agentic_containment import (
    RemoteAgenticContainmentApplyError,
    run_remote_agentic_containment,
)
from tests.support.remote_agentic_containment_fixture import (
    NOW,
    RemoteAgenticContainmentFixture,
)


class RemoteAgenticContainmentTest(RemoteAgenticContainmentFixture, unittest.TestCase):
    def test_dry_run_accounts_for_four_tool_steps_and_one_final_step(self) -> None:
        before = self._state_snapshot()

        report = run_remote_agentic_containment(
            self.provider_store,
            self.runtime_store,
            mode="dry_run",
            now=NOW + timedelta(minutes=1),
        )

        self.assertEqual(self._state_snapshot(), before)
        self.assertEqual(report.mode, "dry_run")
        self.assertEqual(report.implementation_status, "implementation_ready")
        self.assertEqual(report.dry_run_status, "dry_run_verified")
        self.assertEqual(report.operational_status, "live_apply_pending_review")
        self.assertEqual(report.counts["bindings_to_disable"], 1)
        self.assertEqual(report.counts["profiles_to_suspend"], 1)
        self.assertEqual(report.counts["certificates_to_revoke"], 1)
        self.assertEqual(report.counts["sessions_to_quarantine"], 1)
        inventory = report.session_inventory[0]
        self.assertEqual(inventory.provider_acceptance_count, 5)
        self.assertEqual(inventory.ledger_proposal_count, 4)
        self.assertEqual(inventory.ambiguous_provider_step_count, 0)
        self.assertEqual(inventory.unaccounted_provider_acceptance_count, 0)
        self.assertEqual(inventory.execution_unknown_count, 1)
        self.assertNotIn("provider_step_outcome_ambiguous", inventory.reason_codes)
        self.assertIn("tool_execution_unknown", inventory.reason_codes)
        self.assertNotIn("credential-redacted-from-report", str(asdict(report)))
        self.assertEqual(len(report.plan_digest), 64)

    def test_apply_preserves_codex_and_consumes_the_reviewed_plan(self) -> None:
        codex_before = self._codex_snapshot()
        reviewed = run_remote_agentic_containment(
            self.provider_store,
            self.runtime_store,
            mode="dry_run",
            now=NOW,
        )

        first = run_remote_agentic_containment(
            self.provider_store,
            self.runtime_store,
            mode="apply",
            expected_plan_digest=reviewed.plan_digest,
            now=NOW + timedelta(minutes=1),
        )
        applied_state = self._state_snapshot()
        with self.assertRaises(RemoteAgenticContainmentApplyError) as raised:
            run_remote_agentic_containment(
                self.provider_store,
                self.runtime_store,
                mode="apply",
                expected_plan_digest=reviewed.plan_digest,
                now=NOW + timedelta(minutes=2),
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
        self.assertFalse(binding.is_default)
        self.assertEqual(profile_status.rollout_status, "suspended")
        self.assertEqual(certificate_status.status, "revoked")
        self.assertEqual(certificate_status.revocation_reason, "phase" + "0_remote_agentic_containment")
        self.assertEqual(session.status, "recovery_required")
        self.assertEqual(session.recovery_reason_code, "remote_agentic_state_ambiguous")
        projection_state = SimpleNamespace(
            provider_store=self.provider_store,
            provider_registry=self.registry,
        )
        for public_session in (
            runtime_session_payload(session, state=projection_state),
            _session_payload(session, state=projection_state),
        ):
            self.assertEqual(public_session["status"], "recovery_required")
            self.assertEqual(
                public_session["recovery_reason_code"],
                "remote_agentic_state_ambiguous",
            )
            self.assertEqual(public_session["agentic_containment"]["status"], "NO-GO")
            governance = public_session["agentic_governance"]
            self.assertEqual(
                governance["display_name"],
                self.remote_definition.display_name,
            )
            self.assertIn("Full Workspace preview", governance["display_name"])
            self.assertEqual(governance["containment"]["status"], "NO-GO")
            self.assertEqual(
                governance["data_destination"],
                {
                    "provider_id": "google-ai-studio",
                    "endpoint_id": "google-generativelanguage-v1-interactions",
                    "upstream_provider_ids": (),
                    "display_label": (
                        "google-ai-studio · "
                        "google-generativelanguage-v1-interactions"
                    ),
                },
            )
            self.assertEqual(
                governance["egress_policy"],
                {
                    "policy_id": "remote-agentic-contained",
                    "revision": "2",
                    "allowed_remote_data_classes": ("public",),
                },
            )
            self.assertEqual(
                governance["data_policy"],
                {
                    "collection": "provider_contract",
                    "require_zdr": False,
                    "attestation_state": "not_attested",
                    "attestation": {
                        "state": "not_attested",
                        "authoritative": False,
                        "declaration": None,
                        "scope": None,
                        "revision": None,
                        "updated_at": None,
                    },
                },
            )
            self.assertEqual(
                governance["certificate_posture"]["effective_status"],
                "revoked",
            )
            self.assertEqual(
                governance["certificate_posture"]["eligibility"],
                "ineligible",
            )
            self.assertEqual(governance["effective_capabilities"]["status"], "blocked")
            self.assertFalse(any(
                value
                for value in governance["effective_capabilities"]["capabilities"].values()
                if isinstance(value, bool)
            ))
            self.assertNotIn("credential_binding_id", str(public_session))
        settings = workspace_agentic_admin_status(
            SimpleNamespace(
                provider_store=self.provider_store,
                provider_registry=self.registry,
            ),
            workspace_id="default",
        )
        remote_item = next(
            item
            for item in settings["items"]
            if item["definition_id"] == self.remote_definition.definition_id
        )
        self.assertEqual(settings["release_decision"], "NO-GO")
        self.assertEqual(remote_item["containment_status"], "NO-GO")
        self.assertEqual(remote_item["display_name"], self.remote_definition.display_name)
        self.assertEqual(remote_item["model_provider_id"], "google-ai-studio")
        self.assertEqual(
            remote_item["upstream_provider_ids"],
            self.remote_definition.routing_constraint.allowed_upstream_ids,
        )
        self.assertEqual(remote_item["binding_status"], "disabled")
        self.assertEqual(remote_item["profile_status"], "suspended")
        self.assertEqual(remote_item["certificate"]["effective_status"], "revoked")
        self.assertNotIn("revocation_reason", remote_item["certificate"])
        self.assertEqual(remote_item["certificate_eligibility"], "ineligible")
        self.assertEqual(remote_item["effective_capabilities"]["status"], "blocked")
        self.assertEqual(
            remote_item["effective_capabilities"]["tcb"]["posture"],
            "ineligible",
        )
        self.assertEqual(
            remote_item["data_destination"],
            {
                "provider_id": "google-ai-studio",
                "endpoint_id": "google-generativelanguage-v1-interactions",
                "upstream_provider_ids": (),
                "display_label": (
                    "google-ai-studio · "
                    "google-generativelanguage-v1-interactions"
                ),
            },
        )
        self.assertEqual(
            remote_item["egress_policy"],
            {
                "policy_id": "remote-agentic-contained",
                "revision": "2",
                "allowed_remote_data_classes": ("public",),
            },
        )
        self.assertEqual(
            remote_item["data_policy"],
            {
                "collection": "provider_contract",
                "require_zdr": False,
                "attestation_state": "not_attested",
                "attestation": {
                    "state": "not_attested",
                    "authoritative": False,
                    "declaration": None,
                    "scope": None,
                    "revision": None,
                    "updated_at": None,
                },
            },
        )
        self.assertEqual(self._codex_snapshot(), codex_before)
        self.assertEqual(self._state_snapshot(), applied_state)
        self.assertEqual(
            raised.exception.reason_code,
            "remote_agentic_containment_plan_changed",
        )
        self.assertFalse(raised.exception.safe_to_retry)
        self.assertTrue(raised.exception.requires_new_dry_run)
        self.assertEqual(first.counts["bindings_disabled"], 1)
        self.assertEqual(first.counts["sessions_quarantined"], 1)


if __name__ == "__main__":
    unittest.main()
