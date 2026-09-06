"""Create an experimental pin without inventing any certificate metadata."""

from dataclasses import fields, replace
from datetime import UTC, datetime
from uuid import uuid4

from core.certification_lab.errors import LabAuthorizationError
from core.certification_lab.permit import LabApiTarget
from core.providers.certification_target import api_profile_target_digest
from core.runtime.execution_binding import RuntimeExecutionBinding, canonical_digest


# Intentional mapping of technical and policy identities; neither a certificate
# field nor another revision's workspace binding is copied by this projection.
_PROFILE_FIELDS = (
    'runtime_engine_id', 'adapter_id', 'model_provider_id', 'model_id', 'model_revision',
    'model_revision_policy', 'provider_protocol', 'provider_api_version',
    'full_workspace_contract_revision', 'execution_family', 'harness_recipe_id',
    'harness_recipe_revision', 'harness_recipe_digest', 'provider_capability_catalog_digest',
    'semantic_projection_compiler_revision', 'tool_contract_revision', 'provider_config_id',
    'provider_config_revision', 'provider_config_digest', 'protocol_adapter_id', 'protocol_adapter_version',
)


def build_lab_execution_binding(store, *, ownership, definition, workspace_binding, reasoning_effort):
    permit = store.resolve(ownership.reference)
    if (type(permit.target) is not LabApiTarget or permit.target.definition_digest != api_profile_target_digest(definition)
            or permit.target.definition_id != definition.definition_id or permit.target.definition_revision != definition.revision
            or permit.target.model_provider_id != definition.model_provider_id):
        raise LabAuthorizationError('lab_target_mismatch')
    if (workspace_binding.definition_id != definition.definition_id or workspace_binding.definition_revision != definition.revision
            or workspace_binding.workspace_id != permit.workspace.workspace_id or not workspace_binding.enabled
            or workspace_binding.credential_binding_id != permit.credential_binding_id
            or reasoning_effort not in permit.reasoning_efforts):
        raise LabAuthorizationError('lab_binding_identity_mismatch')
    if (permit.routing_constraint != definition.routing_constraint
            or permit.egress_policy_id != definition.egress_policy_id
            or permit.egress_policy_revision != definition.egress_policy_revision):
        raise LabAuthorizationError('lab_route_mismatch')
    record = RuntimeExecutionBinding(
        execution_binding_id=f'lab-runtime-binding-{uuid4().hex}', session_id=ownership.session_id,
        workspace_id=permit.workspace.workspace_id,
        profile_definition_id=definition.definition_id, profile_definition_revision=definition.revision,
        workspace_binding_id=workspace_binding.binding_id, workspace_binding_revision=workspace_binding.revision,
        capability_certificate_id=None, certificate_evidence_digest=None, certified_reasoning_efforts=(),
        default_reasoning_effort=None, reasoning_effort=reasoning_effort,
        adapter_version=permit.candidate.adapter_version, adapter_artifact_digest=permit.candidate.adapter_artifact_digest,
        routing_constraint_snapshot=definition.routing_constraint, credential_binding_id=permit.credential_binding_id,
        # Hosted tools remain Bubblewrap-confined even when the product mode
        # authorizes the Full Workspace shell surface. This is NOT host access.
        execution_mode='full-access', profile_policy_ceiling_snapshot=definition.policy_ceiling,
        workspace_policy_ceiling_snapshot=workspace_binding.workspace_policy_ceiling,
        egress_policy_id=permit.egress_policy_id, egress_policy_revision=permit.egress_policy_revision,
        tool_authority_ceiling_digest=canonical_digest(workspace_binding.workspace_policy_ceiling),
        binding_digest='', created_at=datetime.now(UTC),
        tcb_manifest_id=permit.candidate.tcb_manifest_id, tcb_manifest_version=permit.candidate.tcb_manifest_version,
        tcb_structure_digest=permit.candidate.tcb_structure_digest, tcb_live_digest=permit.candidate.tcb_live_digest,
        context_policy_snapshot=definition.context_policy,
        authorization_domain='certification_lab', lab_permit_reference=ownership.reference,
        lab_reasoning_efforts=permit.reasoning_efforts,
        **{name: getattr(definition, name) for name in _PROFILE_FIELDS},
    )
    if record.adapter_id != permit.candidate.adapter_id:
        raise LabAuthorizationError('lab_adapter_mismatch')
    record = replace(record, binding_digest=canonical_digest(record))
    store.bind(ownership, binding_digest=record.binding_digest)
    return record


def validate_lab_profile_pin(binding, *, permit, definition):
    if (type(permit.target) is not LabApiTarget or permit.target.definition_digest != api_profile_target_digest(definition)
            or binding.profile_definition_id != definition.definition_id
            or binding.profile_definition_revision != definition.revision
            or any(getattr(binding, name) != getattr(definition, name) for name in _PROFILE_FIELDS)
            or binding.context_policy_snapshot != definition.context_policy
            or binding.profile_policy_ceiling_snapshot != definition.policy_ceiling
            or binding.routing_constraint_snapshot != permit.routing_constraint
            or binding.routing_constraint_snapshot != definition.routing_constraint
            or binding.egress_policy_id != permit.egress_policy_id
            or binding.egress_policy_revision != permit.egress_policy_revision
            or binding.credential_binding_id != permit.credential_binding_id
            or binding.reasoning_effort not in permit.reasoning_efforts):
        raise LabAuthorizationError('lab_binding_identity_mismatch')
    for field in fields(permit.candidate):
        if field.name != 'source_commit' and getattr(binding, field.name) != getattr(permit.candidate, field.name):
            raise LabAuthorizationError('lab_candidate_mismatch')
