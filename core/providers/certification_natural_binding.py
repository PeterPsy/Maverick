"""Execution-binding projection for natural certification."""

from __future__ import annotations

from core.providers.certification_natural_artifacts import artifact_sha256
from core.providers.certification_natural_lab import certification_natural_lab_permit_payload
from core.runtime.execution_binding import build_runtime_execution_binding

def build_binding(
    definition,
    workspace_binding,
    credential_binding,
    session_id,
    effort,
    permit,
    adapter_version,
    now,
):
    return build_runtime_execution_binding(
        session_id=session_id,
        workspace_id=workspace_binding.workspace_id,
        profile_definition_id=definition.definition_id,
        profile_definition_revision=definition.revision,
        workspace_binding_id=workspace_binding.binding_id,
        workspace_binding_revision=workspace_binding.revision,
        capability_certificate_id=f"certification-lab:{permit.permit_id}",
        runtime_engine_id=definition.runtime_engine_id,
        adapter_id=definition.adapter_id,
        adapter_version=adapter_version,
        adapter_artifact_digest=permit.adapter_artifact_digest,
        model_provider_id=definition.model_provider_id,
        model_id=definition.model_id,
        model_revision=definition.model_revision,
        model_revision_policy=definition.model_revision_policy,
        provider_protocol=definition.provider_protocol,
        provider_api_version=definition.provider_api_version,
        routing_constraint=definition.routing_constraint,
        credential_binding_id=credential_binding.binding_id,
        reasoning_effort=effort,
        certified_reasoning_efforts=(effort,),
        default_reasoning_effort=effort,
        execution_mode="full-access",
        profile_policy_ceiling=definition.policy_ceiling,
        workspace_policy_ceiling=workspace_binding.workspace_policy_ceiling,
        egress_policy_id=workspace_binding.egress_policy_id,
        egress_policy_revision=workspace_binding.egress_policy_revision,
        certificate_evidence_digest=artifact_sha256(
            certification_natural_lab_permit_payload(permit)
        ),
        created_at=now,
        tcb_manifest_id=permit.tcb_manifest_id,
        tcb_manifest_version=permit.tcb_manifest_version,
        tcb_structure_digest=permit.tcb_structure_digest,
        tcb_live_digest=permit.tcb_live_digest,
        full_workspace_contract_revision=definition.full_workspace_contract_revision,
        execution_family=definition.execution_family,
        harness_recipe_id=definition.harness_recipe_id,
        harness_recipe_revision=definition.harness_recipe_revision,
        harness_recipe_digest=definition.harness_recipe_digest,
        provider_capability_catalog_digest=definition.provider_capability_catalog_digest,
        semantic_projection_compiler_revision=(
            definition.semantic_projection_compiler_revision
        ),
        tool_contract_revision=definition.tool_contract_revision,
        context_policy=definition.context_policy,
        provider_config_id=definition.provider_config_id,
        provider_config_revision=definition.provider_config_revision,
        provider_config_digest=definition.provider_config_digest,
        protocol_adapter_id=definition.protocol_adapter_id,
        protocol_adapter_version=definition.protocol_adapter_version,
    )




__all__ = ["build_binding"]
