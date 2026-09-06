"""Deterministic certification fixtures for agentic runtime tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from core.providers.agentic_models import (
    AgenticProfileDefinitionStatus,
    WorkspaceAgenticProfileBinding,
    default_actor_selection_policy,
)
from core.providers.capability_models import CapabilityCertificate, RuntimeCapabilitySet
from core.providers.certificate_service import (
    build_capability_evidence,
    publish_capability_certificate,
    runtime_adapter_artifact_digest,
)
from core.providers.certified_execution_tcb import certified_tcb_identity
from core.providers.certification_target import api_profile_target_digest
from core.providers.store import ProviderCollections, ProviderDocumentStore
from core.runtime.authority import resolve_effective_runtime_authority
from core.runtime.execution_binding import RuntimeExecutionBinding, canonical_digest
from tests.support.collections import FakeCollection


def fake_capability_evidence(adapter: object, *, now: datetime, definition=None):
    artifact_digest = runtime_adapter_artifact_digest(adapter)
    tcb = certified_tcb_identity()
    return build_capability_evidence(
        suite_id="fake-agentic-contract",
        suite_version="1",
        test_run_id=f"fake-run:{artifact_digest[:16]}",
        adapter_artifact_digest=artifact_digest,
        result_summary_digest=canonical_digest({"result": "passed"}),
        evidence_refs=("platform-evidence:test:fake-agentic-contract",),
        recorded_at=now,
        certification_target_digest=("" if definition is None else api_profile_target_digest(definition)),
        tcb_manifest_id=tcb.manifest_id,
        tcb_manifest_version=tcb.manifest_version,
        tcb_structure_digest=tcb.structure_digest,
        tcb_live_digest=tcb.live_digest,
    )


def certified_test_provider_store(
    binding: RuntimeExecutionBinding,
    adapter: object,
    *,
    evidence,
    now: datetime,
    validity_days: int = 1,
    definition=None,
    certified_capabilities: RuntimeCapabilitySet | None = None,
) -> ProviderDocumentStore:
    store = ProviderDocumentStore(
        ProviderCollections(
            definitions=FakeCollection(),
            agentic_profile_definitions=FakeCollection(),
            bindings=FakeCollection(),
            selections=FakeCollection(),
            agentic_profile_definition_statuses=FakeCollection(),
            workspace_agentic_profile_bindings=FakeCollection(),
            capability_evidence=FakeCollection(),
            capability_certificates=FakeCollection(),
            capability_certificate_statuses=FakeCollection(),
        )
    )
    if definition is not None:
        store.save_agentic_profile_definition(definition)
    store.save_agentic_profile_definition_status(
        AgenticProfileDefinitionStatus(
            definition_id=binding.profile_definition_id,
            definition_revision=binding.profile_definition_revision,
            rollout_status="preview",
            revision=0,
            updated_at=now,
        ),
        expected_revision=None,
    )
    store.save_workspace_agentic_profile_binding(
        WorkspaceAgenticProfileBinding(
            binding_id=binding.workspace_binding_id,
            workspace_id=binding.workspace_id,
            definition_id=binding.profile_definition_id,
            definition_revision=binding.profile_definition_revision,
            credential_binding_id=binding.credential_binding_id,
            enabled=True,
            is_default=True,
            actor_policy=default_actor_selection_policy(),
            workspace_policy_ceiling=binding.workspace_policy_ceiling_snapshot,
            egress_policy_id=binding.egress_policy_id,
            egress_policy_revision=binding.egress_policy_revision,
            revision=binding.workspace_binding_revision,
            created_at=now,
            updated_at=now,
        ),
        expected_revision=None,
    )
    publish_capability_certificate(
        store,
        evidence=evidence,
        certificate=CapabilityCertificate(
            certificate_id=binding.capability_certificate_id,
            schema_version="1",
            runtime_engine_id=binding.runtime_engine_id,
            adapter_id=binding.adapter_id,
            adapter_version=binding.adapter_version,
            adapter_artifact_digest=binding.adapter_artifact_digest,
            model_provider_id=binding.model_provider_id,
            model_id=binding.model_id,
            model_revision=binding.model_revision,
            provider_protocol=binding.provider_protocol,
            provider_api_version=binding.provider_api_version,
            certified_upstream_ids=binding.routing_constraint_snapshot.allowed_upstream_ids,
            routing_constraint_digest=canonical_digest(binding.routing_constraint_snapshot),
            certified_capabilities=certified_capabilities
            or RuntimeCapabilitySet(
                streaming=True,
                tool_orchestration=True,
                cli=True,
                mcp=True,
                skill_catalog=True,
                filesystem_list=True,
                filesystem_read=True,
                filesystem_write=True,
                shell=True,
                interrupt=True,
                same_turn_steering=False,
                recovery=True,
                confirmation_resume=True,
                provider_private_state=True,
                attachment_modalities=(),
            ),
            certified_reasoning_efforts=binding.certified_reasoning_efforts,
            default_reasoning_effort=binding.default_reasoning_effort,
            suite_id=evidence.suite_id,
            suite_version=evidence.suite_version,
            test_run_id=evidence.test_run_id,
            evidence_digest=evidence.evidence_digest,
            certification_target_digest=evidence.certification_target_digest,
            evidence_refs=evidence.evidence_refs,
            issued_at=now,
            expires_at=now + timedelta(days=validity_days),
            tcb_manifest_id=evidence.tcb_manifest_id,
            tcb_manifest_version=evidence.tcb_manifest_version,
            tcb_structure_digest=evidence.tcb_structure_digest,
            tcb_live_digest=evidence.tcb_live_digest,
            full_workspace_contract_revision=(
                binding.full_workspace_contract_revision
            ),
            execution_family=binding.execution_family,
            harness_recipe_id=binding.harness_recipe_id,
            harness_recipe_revision=binding.harness_recipe_revision,
            harness_recipe_digest=binding.harness_recipe_digest,
            provider_capability_catalog_digest=(
                binding.provider_capability_catalog_digest
            ),
            semantic_projection_compiler_revision=(
                binding.semantic_projection_compiler_revision
            ),
            tool_contract_revision=binding.tool_contract_revision,
            context_policy_revision=(
                ""
                if binding.context_policy_snapshot is None
                else binding.context_policy_snapshot.revision
            ),
            model_revision_policy=binding.model_revision_policy,
            provider_config_id=binding.provider_config_id,
            provider_config_revision=binding.provider_config_revision,
            provider_config_digest=binding.provider_config_digest,
            protocol_adapter_id=binding.protocol_adapter_id,
            protocol_adapter_version=binding.protocol_adapter_version,
        ),
    )
    return store


def certified_test_authority(store, binding, adapter, *, turn_id: str, now: datetime):
    return resolve_effective_runtime_authority(
        store,
        binding=binding,
        adapter=adapter,
        turn_id=turn_id,
        now=now,
    )
