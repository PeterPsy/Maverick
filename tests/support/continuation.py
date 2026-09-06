"""Shared fixtures for runtime continuation tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import os
from unittest.mock import patch

from core.api.platform_state import bootstrap_platform_state
from core.providers.agentic_profiles import build_pinned_execution_binding
from core.providers.certificate_service import (
    build_capability_evidence,
    publish_capability_certificate,
)
from core.providers.certification_target import api_profile_target_digest
from core.runtime.execution_binding import (
    build_runtime_execution_binding,
    canonical_digest,
)
from core.runtime.runtime_threads import create_runtime_thread
from core.runtime.service import create_runtime_session, transition_runtime_session
from tests.support.repo import make_temp_repo_root
from tests.support.continuation_profiles import install_continuation_target


NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


class RuntimeContinuationFixture:
    """Exercise generic handoff with offline API tuples, not forged native roots."""

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
        self.target = install_continuation_target(self.state, now=NOW)
        # Only the external release gate is replaced in this isolated store.
        # Certificates, exact targets, TCB, governance and handoff proofs stay real;
        # the registered adapter cannot dispatch any network/process request.
        containment = patch(
            "core.runtime.remote_agentic_admission.remote_agentic_containment_reason",
            return_value=None,
        )
        containment.start()
        self.addCleanup(containment.stop)

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
        target_workspace_binding_id: str | None = None,
    ):
        target = build_pinned_execution_binding(
            self.state.provider_store,
            self.state.provider_registry,
            session_id=f"{session_id}-target-template",
            workspace_id="default",
            execution_mode="full-access",
            workspace_binding_id=target_workspace_binding_id or self.target.workspace_binding_id,
            now=NOW,
        )
        target_certificate = self.state.provider_store.get_capability_certificate(
            target.capability_certificate_id
        )
        target_profile = self.state.provider_store.get_agentic_profile_definition(
            target.profile_definition_id, target.profile_definition_revision,
        )
        source_routing = (
            replace(target.routing_constraint_snapshot, allowed_upstream_ids=("incompatible-upstream",))
            if routing_mismatch else target.routing_constraint_snapshot
        )
        source_profile = replace(
            target_profile,
            revision=f"obsolete:{session_id}",
            capability_certificate_id=f"old-certificate:{session_id}",
            model_id=source_model_id or target.model_id,
            routing_constraint=source_routing,
        )
        self.state.provider_store.save_agentic_profile_definition(source_profile)
        old_artifact_digest = "2" * 64
        old_evidence = build_capability_evidence(
            suite_id=target_certificate.suite_id,
            suite_version=target_certificate.suite_version,
            test_run_id=f"old-revision:{session_id}",
            adapter_artifact_digest=old_artifact_digest,
            result_summary_digest=canonical_digest({"session_id": session_id}),
            evidence_refs=target_certificate.evidence_refs,
            recorded_at=NOW,
            certification_target_digest=(
                api_profile_target_digest(source_profile)
                if source_profile.execution_family == "maverick_agent" else ""
            ),
            **{name: getattr(target_certificate, name) for name in (
                "tcb_manifest_id", "tcb_manifest_version", "tcb_structure_digest", "tcb_live_digest",
            )},
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
            certification_target_digest=old_evidence.certification_target_digest,
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
            profile_definition_revision=source_profile.revision,
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
                        target.workspace_policy_ceiling_snapshot.max_steps_per_turn
                        - 1,
                    ),
                )
                if policy_mismatch
                else target.workspace_policy_ceiling_snapshot
            ),
            egress_policy_id=(
                "incompatible-egress-policy"
                if egress_mismatch
                else target.egress_policy_id
            ),
            egress_policy_revision=target.egress_policy_revision,
            certificate_evidence_digest=old_certificate.evidence_digest,
            created_at=NOW,
            legacy_inferred=legacy_inferred,
            context_policy=source_profile.context_policy,
            **{name: getattr(source_profile, name) for name in (
                "model_revision", "model_revision_policy", "full_workspace_contract_revision",
                "execution_family", "harness_recipe_id", "harness_recipe_revision", "harness_recipe_digest",
                "provider_capability_catalog_digest", "semantic_projection_compiler_revision",
                "tool_contract_revision", "provider_config_id", "provider_config_revision",
                "provider_config_digest", "protocol_adapter_id", "protocol_adapter_version",
            )},
        )
        source = create_runtime_session(
            self.state.runtime_store,
            session_id=session_id,
            workspace_id="default",
            agent_id="chat",
            source_app_id="chat",
            thread_title="Continuation test",
            agent_label="Offline continuation fixture",
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
                agent_label="Offline continuation fixture",
                source_app_id="chat",
                system_prompt="",
                now=NOW,
            )
        return self.state.runtime_store.get_session(session_id)
