from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import core.runtime.turn_submission_service_runtime as async_submission
import core.runtime.turn_submission_service_submit as sync_submission

from core.providers.agentic_adapter import RuntimeHealth
from core.providers.agentic_models import codex_routing_constraint, codex_runtime_policy
from core.providers.capability_models import RuntimeCapabilitySet
from core.providers.certificate_service import (
    revoke_capability_certificate,
    runtime_adapter_artifact_digest,
)
from core.providers.errors import CapabilityCertificateError
from core.runtime.authority import (
    blocked_runtime_capability_payload,
    effective_runtime_capability_payload,
    intersect_runtime_capabilities,
    resolve_effective_runtime_authority,
    validate_effective_context_capabilities,
)
from core.runtime.execution_binding import (
    build_runtime_execution_binding,
    canonical_digest,
)
from core.runtime.authority_service import revalidate_runtime_authority_snapshot
from core.runtime.failure_messages import runtime_failure_public_message
from tests.support.agentic_certification import (
    certified_test_provider_store,
    fake_capability_evidence,
)
from tests.support.fake_agentic_adapter import FakeHostedAgenticAdapter


NOW = datetime(2026, 8, 26, tzinfo=UTC)


def capabilities(**updates: object) -> RuntimeCapabilitySet:
    values: dict[str, object] = {
        "streaming": True,
        "tool_orchestration": True,
        "cli": True,
        "mcp": True,
        "skill_catalog": True,
        "filesystem_list": True,
        "filesystem_read": True,
        "filesystem_write": True,
        "shell": True,
        "interrupt": True,
        "same_turn_steering": True,
        "recovery": True,
        "confirmation_resume": True,
        "provider_private_state": True,
        "attachment_modalities": ("text", "image"),
        "app_references": True,
        "confirmations": True,
    }
    values.update(updates)
    return RuntimeCapabilitySet(**values)


class EffectiveCapabilitiesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = FakeHostedAgenticAdapter()
        self.evidence = fake_capability_evidence(self.adapter, now=NOW)
        self.binding = build_runtime_execution_binding(
            session_id="session-effective",
            workspace_id="default",
            profile_definition_id="profile-effective",
            profile_definition_revision="1",
            workspace_binding_id="workspace-effective",
            workspace_binding_revision=0,
            capability_certificate_id="certificate-effective",
            runtime_engine_id=self.adapter.runtime_engine_id,
            adapter_id=self.adapter.adapter_id,
            adapter_version=self.adapter.adapter_version,
            adapter_artifact_digest=runtime_adapter_artifact_digest(self.adapter),
            model_provider_id="fake-provider",
            model_id="fake-model",
            provider_protocol="fake-stream-v1",
            provider_api_version="v1",
            routing_constraint=codex_routing_constraint(),
            credential_binding_id=None,
            reasoning_effort=None,
            certified_reasoning_efforts=(),
            default_reasoning_effort=None,
            execution_mode="full-access",
            profile_policy_ceiling=codex_runtime_policy(),
            workspace_policy_ceiling=codex_runtime_policy(),
            egress_policy_id="fake-egress",
            egress_policy_revision="1",
            certificate_evidence_digest=self.evidence.evidence_digest,
            created_at=NOW,
        )
        self.store = certified_test_provider_store(
            self.binding,
            self.adapter,
            evidence=self.evidence,
            now=NOW,
        )

    def test_intersection_never_overstates_any_input(self) -> None:
        certificate = capabilities()
        profile = capabilities(cli=False, attachment_modalities=("text",))
        workspace = capabilities(filesystem_write=False, shell=False)
        actor = capabilities(mcp=False, app_references=False)
        live = capabilities(skill_catalog=False, confirmations=False)
        features = capabilities(provider_private_state=False)
        health = capabilities(recovery=False, tool_orchestration=False)

        effective = intersect_runtime_capabilities(
            certificate,
            profile,
            workspace,
            actor,
            live,
            features,
            health,
        )

        for field_name, value in effective.__dict__.items():
            if isinstance(value, bool) and value:
                self.assertTrue(
                    all(getattr(item, field_name) for item in (
                        certificate, profile, workspace, actor, live, features, health
                    )),
                    field_name,
                )
        self.assertEqual(effective.attachment_modalities, ("text",))
        self.assertFalse(effective.cli)
        self.assertFalse(effective.filesystem_write)
        self.assertFalse(effective.app_references)
        self.assertFalse(effective.provider_private_state)
        self.assertFalse(effective.recovery)

    def test_blocked_projection_allowlists_reason_codes(self) -> None:
        known = blocked_runtime_capability_payload("hosted_agent_runtime_disabled")
        unknown = blocked_runtime_capability_payload(
            "private_runtime_path_srv_secret_token"
        )

        self.assertEqual(known["reason_code"], "hosted_agent_runtime_disabled")
        self.assertEqual(unknown["reason_code"], "runtime_authority_unavailable")
        self.assertNotIn("secret", str(unknown))

    def test_actor_features_health_and_live_authority_are_intersected(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "MAVERICK_FEATURE_AGENTIC_TOOL_CONFIRMATION": "0",
                "MAVERICK_FEATURE_PROVIDER_PRIVATE_STATE": "0",
            },
            clear=False,
        ):
            authority = resolve_effective_runtime_authority(
                self.store,
                binding=self.binding,
                adapter=self.adapter,
                turn_id="turn-effective",
                currently_authorized_tool_handles=(
                    "core-capability:filesystem.read",
                ),
                health_status="degraded",
                health_revision="health:degraded:1",
                actor_policy_allowed=True,
                actor_policy_revision="actor:1",
                now=NOW,
            )

        self.assertTrue(authority.allowed_capabilities.streaming)
        self.assertFalse(authority.allowed_capabilities.tool_orchestration)
        self.assertFalse(authority.allowed_capabilities.filesystem_write)
        self.assertFalse(authority.allowed_capabilities.shell)
        self.assertFalse(authority.allowed_capabilities.recovery)
        self.assertFalse(authority.allowed_capabilities.confirmations)
        self.assertFalse(authority.allowed_capabilities.provider_private_state)
        self.assertEqual(authority.provider_health_status, "degraded")
        self.assertEqual(authority.actor_policy_revision, "actor:1")
        projection = effective_runtime_capability_payload(authority)
        self.assertNotIn("credential", str(projection).lower())
        self.assertEqual(projection["certificate"]["suite_id"], self.evidence.suite_id)
        self.assertEqual(projection["tcb"]["posture"], "active")

        with self.assertRaisesRegex(
            CapabilityCertificateError,
            "runtime_actor_policy_denied",
        ):
            resolve_effective_runtime_authority(
                self.store,
                binding=self.binding,
                adapter=self.adapter,
                turn_id="turn-actor-denied",
                actor_policy_allowed=False,
                now=NOW,
            )

    def test_empty_hosted_live_tool_authority_never_falls_back_to_certificate(self) -> None:
        authority = resolve_effective_runtime_authority(
            self.store,
            binding=self.binding,
            adapter=self.adapter,
            turn_id="turn-no-live-tools",
            currently_authorized_tool_handles=(),
            now=NOW,
        )

        self.assertEqual(authority.allowed_tool_handles, ())
        self.assertFalse(authority.allowed_capabilities.tool_orchestration)
        self.assertFalse(authority.allowed_capabilities.cli)
        self.assertFalse(authority.allowed_capabilities.mcp)
        self.assertFalse(authority.allowed_capabilities.filesystem_read)
        self.assertFalse(authority.allowed_capabilities.filesystem_write)
        self.assertFalse(authority.allowed_capabilities.shell)

    def test_lightweight_authority_revalidation_fences_tcb_and_revocation(self) -> None:
        health = RuntimeHealth(status="healthy")
        authority = resolve_effective_runtime_authority(
            self.store,
            binding=self.binding,
            adapter=self.adapter,
            turn_id="turn-live-fence",
            health_revision=f"runtime-health:{canonical_digest(health)}",
            actor_policy_revision="actor:live:1",
            now=NOW,
        )
        session = SimpleNamespace(
            execution_binding=self.binding,
            effective_mode="full-access",
            owner_user_id="user-1",
            workspace_id="default",
            agent_type_id="chat",
        )
        state = SimpleNamespace(provider_store=self.store)
        arguments = {
            "state": state,
            "session": session,
            "adapter": self.adapter,
            "authority": authority,
            "now": NOW,
        }
        with patch(
            "core.runtime.authority_service.live_runtime_actor_policy",
            return_value=(True, "actor:live:1"),
        ), patch(
            "core.runtime.authority_service.certified_tcb_revision_fence",
            return_value=authority.tcb_revision_fence,
        ), patch(
            "core.runtime.full_workspace_contract.validate_full_workspace_live_authority",
            side_effect=AssertionError("expensive behavior gate reran"),
        ):
            self.assertIs(
                revalidate_runtime_authority_snapshot(**arguments),
                authority,
            )

        status = self.store.get_capability_certificate_status(
            authority.certificate_id
        )
        self.assertIsNotNone(status)
        revoke_capability_certificate(
            self.store,
            certificate_id=authority.certificate_id,
            expected_revision=status.revision,
            reason="test-revocation",
            now=NOW,
        )
        with self.assertRaisesRegex(
            CapabilityCertificateError,
            "certificate_revoked",
        ):
            revalidate_runtime_authority_snapshot(**arguments)

    def test_sandbox_execution_mode_removes_shell_from_snapshot_and_handles(self) -> None:
        authority = resolve_effective_runtime_authority(
            self.store,
            binding=self.binding,
            adapter=self.adapter,
            turn_id="turn-sandbox-ceiling",
            currently_authorized_tool_handles=(
                "core-capability:filesystem.read",
                "core-capability:shell.run",
            ),
            live_execution_mode="sandbox",
            now=NOW,
        )

        self.assertEqual(authority.execution_mode, "sandbox")
        self.assertTrue(authority.allowed_capabilities.filesystem_read)
        self.assertFalse(authority.allowed_capabilities.shell)
        self.assertEqual(
            authority.allowed_tool_handles,
            ("core-capability:filesystem.read",),
        )

    def test_required_but_ineffective_confirmations_remove_all_tool_authority(self) -> None:
        live = self.store.get_workspace_agentic_profile_binding(
            self.binding.workspace_binding_id
        )
        confirmation_policy = replace(
            live.workspace_policy_ceiling,
            require_confirmation_for_mutating=True,
        )
        self.store.save_workspace_agentic_profile_binding(
            replace(
                live,
                workspace_policy_ceiling=confirmation_policy,
                revision=live.revision + 1,
                updated_at=NOW,
            ),
            expected_revision=live.revision,
        )
        authority = resolve_effective_runtime_authority(
            self.store,
            binding=self.binding,
            adapter=self.adapter,
            turn_id="turn-confirmation-ceiling",
            currently_authorized_tool_handles=(
                "core-capability:filesystem.read",
                "core-capability:filesystem.write",
            ),
            now=NOW,
        )

        self.assertFalse(authority.allowed_capabilities.confirmations)
        self.assertFalse(authority.allowed_capabilities.tool_orchestration)
        self.assertFalse(authority.allowed_capabilities.filesystem_read)
        self.assertFalse(authority.allowed_capabilities.filesystem_write)
        self.assertEqual(authority.allowed_tool_handles, ())

    def test_unsupported_context_has_public_reason_before_use(self) -> None:
        base = resolve_effective_runtime_authority(
            self.store,
            binding=self.binding,
            adapter=self.adapter,
            turn_id="turn-context",
            now=NOW,
        )
        denied = replace(
            base,
            allowed_capabilities=replace(
                base.allowed_capabilities,
                skill_catalog=False,
                attachment_modalities=("text",),
                app_references=False,
                cli=False,
                mcp=False,
                shell=False,
                filesystem_write=False,
            ),
            authority_digest="",
        )
        cases = (
            ({"invoked_skills": ("skill",)}, "agentic_skill_catalog_not_effective"),
            (
                {"attachments": ({"content_type": "image/png"},)},
                "agentic_attachment_modality_not_certified",
            ),
            ({"attachments": ({"name": "missing-type"},)}, "agentic_attachment_metadata_invalid"),
            ({"app_references": ({"app_id": "crm"},)}, "agentic_app_references_not_effective"),
            ({"requested_operations": ("cli",)}, "agentic_cli_not_effective"),
            ({"requested_operations": ("mcp",)}, "agentic_mcp_not_effective"),
            ({"requested_operations": ("shell",)}, "agentic_shell_not_effective"),
            (
                {"requested_operations": ("filesystem_write",)},
                "agentic_filesystem_write_not_effective",
            ),
        )
        for arguments, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(
                CapabilityCertificateError,
                reason,
            ):
                validate_effective_context_capabilities(denied, **arguments)

    def test_malformed_context_is_never_coerced_or_silently_filtered(self) -> None:
        authority = resolve_effective_runtime_authority(
            self.store,
            binding=self.binding,
            adapter=self.adapter,
            turn_id="turn-malformed-context",
            now=NOW,
        )
        cases = (
            ({"invoked_skills": {"skill_id": "not-a-sequence"}}, "agentic_skill_metadata_invalid"),
            ({"invoked_skills": (7,)}, "agentic_skill_metadata_invalid"),
            ({"attachments": {"content_type": "image/png"}}, "agentic_attachment_metadata_invalid"),
            ({"attachments": ("not-an-object",)}, "agentic_attachment_metadata_invalid"),
            ({"app_references": ("not-an-object",)}, "agentic_app_reference_metadata_invalid"),
        )
        for arguments, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(
                CapabilityCertificateError,
                reason,
            ):
                validate_effective_context_capabilities(authority, **arguments)
            self.assertNotEqual(
                runtime_failure_public_message(reason),
                "The runtime could not complete this request.",
            )


class RuntimeContextPrePersistenceTest(unittest.TestCase):
    def test_sync_and_async_submission_reject_context_before_queue_or_provider_work(self) -> None:
        session = SimpleNamespace(execution_binding=object())
        state = SimpleNamespace(repository_root="/repo", provider_store=object())
        adapter = SimpleNamespace()
        resolved = (
            SimpleNamespace(provider_id="hosted-fixture"),
            None,
            adapter,
            None,
        )
        skills = (SimpleNamespace(skill_id="fixture-skill"),)
        context = {
            "attachments": [{"content_type": "image/png"}],
            "app_references": [{"app_id": "crm"}],
            "invoked_skill_ids": ["fixture-skill"],
        }

        for module, submit_name in (
            (sync_submission, "submit_runtime_turn"),
            (async_submission, "submit_runtime_turn_async"),
        ):
            queue = Mock()
            provider_work = Mock()
            with self.subTest(submit_name=submit_name), patch.object(
                module,
                "runtime_session_is_plain_hosted_chat",
                return_value=False,
            ), patch.object(
                module,
                "assert_plain_hosted_chat_input_allowed",
            ), patch.object(
                module,
                "resolve_invoked_runtime_skills",
                return_value=skills,
            ), patch.object(
                module,
                "resolve_runtime_engine_for_session",
                return_value=resolved,
            ), patch.object(
                module,
                "preflight_runtime_context_capabilities",
                side_effect=CapabilityCertificateError(
                    "agentic_attachment_modality_not_certified"
                ),
            ) as preflight, patch.object(
                module,
                "_queue_turn_with_event_result",
                queue,
            ), patch.object(
                module,
                "execute_runtime_turn",
                provider_work,
            ):
                with self.assertRaisesRegex(
                    CapabilityCertificateError,
                    "agentic_attachment_modality_not_certified",
                ):
                    getattr(module, submit_name)(
                        state,
                        session=session,
                        input_text="must not persist",
                        **context,
                    )

            preflight.assert_called_once()
            self.assertEqual(preflight.call_args.kwargs["invoked_skills"], skills)
            self.assertEqual(
                preflight.call_args.kwargs["attachments"],
                context["attachments"],
            )
            self.assertEqual(
                preflight.call_args.kwargs["app_references"],
                context["app_references"],
            )
            queue.assert_not_called()
            provider_work.assert_not_called()


if __name__ == "__main__":
    unittest.main()
