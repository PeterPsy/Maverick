"""Validated experimental authority over the production monotonic lattice."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from core.certification_lab.errors import LabAuthorizationError
from core.certification_lab.execution_binding import validate_lab_profile_pin
from core.certification_lab.isolation import directory_identity
from core.certification_lab.permit import LabApiTarget
from core.providers.certificate_service import runtime_adapter_artifact_digest
from core.providers.certified_execution_tcb import certified_tcb_identity, certified_tcb_revision_fence
from core.providers.provider_credentials import resolve_provider_binding
from core.runtime.authority import EffectiveRuntimeAuthority
from core.runtime.authority_lattice import restrict_runtime_authority_ceiling
from core.runtime.execution_binding import canonical_digest


@dataclass(frozen=True)
class LabRuntimeAuthorization:
    """Bootstrap-owned dependencies, never fields accepted from an API/model."""

    permit_store: object
    ownership: object
    workspace_store: object
    provider_store: object
    runtime_store: object
    ledger: object
    repository_root: Path
    source_commit: str
    evidence: object

    def validate_binding(self, binding):
        if (binding is None or binding.authorization_domain != 'certification_lab'
                or binding.lab_permit_reference != self.ownership.reference
                or binding.binding_digest != canonical_digest(binding)
                or binding.session_id != self.ownership.session_id):
            raise LabAuthorizationError('lab_binding_identity_mismatch')
        permit = self.permit_store.validate_ownership(self.ownership, binding_digest=binding.binding_digest)
        if type(permit.target) is not LabApiTarget:
            raise LabAuthorizationError('lab_native_worker_required')
        if (self.source_commit != permit.candidate.source_commit
                or binding.workspace_id != permit.workspace.workspace_id
                or permit.workspace.root_path != str(self.repository_root / 'workspaces' / binding.workspace_id)
                or directory_identity(Path(permit.workspace.root_path)) != permit.workspace.root_identity):
            raise LabAuthorizationError('lab_workspace_identity_mismatch')
        attestation = self.workspace_store.get_data_attestation(binding.workspace_id)
        if (attestation is None or not attestation.authoritative or attestation.scope_type != 'workspace'
                or attestation.attestation_id != permit.workspace.attestation_id
                or attestation.revision != permit.workspace.attestation_revision):
            raise LabAuthorizationError('lab_attestation_changed')
        definition = self.provider_store.get_agentic_profile_definition(binding.profile_definition_id, binding.profile_definition_revision)
        validate_lab_profile_pin(binding, permit=permit, definition=definition)
        credential = resolve_provider_binding(
            self.provider_store, provider_id=binding.model_provider_id,
            workspace_id=binding.workspace_id, binding_id=binding.credential_binding_id,
        )
        if credential is None or canonical_digest(credential) != permit.credential_binding_digest:
            raise LabAuthorizationError('lab_credential_binding_changed')
        if (self.ledger.identity_digest != permit.budget.ledger_identity
                or self.ledger.policy_digest != permit.budget.policy_digest):
            raise LabAuthorizationError('lab_budget_identity_mismatch')
        status = self.ledger.status().get(binding.model_provider_id)
        if (status is None or status['max_cost_microusd'] > permit.budget.max_cost_microusd
                or status['max_requests'] > permit.budget.max_requests or status['halt_reason']):
            raise LabAuthorizationError('lab_budget_policy_mismatch')
        return permit

    def validate_session(self, session):
        permit = self.validate_binding(session.execution_binding)
        current = self.runtime_store.get_session(session.session_id)
        for candidate in (session, current):
            if (candidate.session_id != self.ownership.session_id
                    or candidate.authorization_domain != 'certification_lab'
                    or candidate.lab_installation_id != permit.installation_id
                    or candidate.execution_binding != session.execution_binding
                    or candidate.owner_user_id != permit.workspace.actor_id
                    or candidate.created_by_user_id != permit.workspace.actor_id
                    or candidate.workspace_id != permit.workspace.workspace_id
                    or candidate.workspace_root != permit.workspace.root_path
                    or candidate.runtime_root != str(Path(permit.workspace.root_path) / 'runtime')
                    or candidate.workdir != permit.workspace.root_path
                    or candidate.effective_mode != 'full-access' or candidate.runtime_mode != 'agentic'
                    or candidate.status not in {'created', 'running'}
                    or candidate.creator_runtime_session_id is not None):
                raise LabAuthorizationError('lab_session_identity_changed')
        return permit

    def resolve(self, *, session, adapter, turn_id, tool_handles, health, actor_allowed, actor_revision):
        permit = self.validate_session(session)
        binding = session.execution_binding
        live = self.validate_candidate(adapter)
        restricted = restrict_runtime_authority_ceiling(
            self.provider_store, binding=binding, capability_ceiling=permit.capability_ceiling,
            currently_authorized_tool_handles=tool_handles, live_execution_mode=session.effective_mode,
            health_status=health.status, actor_policy_allowed=actor_allowed,
            additional_policy_ceilings=(permit.policy_ceiling,),
        )
        authority = EffectiveRuntimeAuthority(
            execution_binding_id=binding.execution_binding_id, turn_id=turn_id, certificate_id=None,
            allowed_capabilities=restricted.capabilities, allowed_tool_handles=restricted.tool_handles,
            execution_mode=restricted.execution_mode, egress_policy_id=binding.egress_policy_id,
            policy_revision_set=(
                f'profile:{binding.profile_definition_id}:{binding.profile_definition_revision}',
                f'workspace-live:{restricted.workspace_binding.binding_id}:{restricted.workspace_binding.revision}',
                f'lab-permit:{permit.permit_id}:{binding.lab_permit_reference.status_revision}',
                f'egress:{binding.egress_policy_id}:{binding.egress_policy_revision}',
            ),
            health_revision=f'runtime-health:{canonical_digest(health)}', authority_digest='', computed_at=datetime.now(UTC),
            actor_policy_allowed=actor_allowed, actor_policy_revision=actor_revision,
            feature_flag_revision=restricted.feature_revision, provider_health_status=health.status,
            provider_id=binding.model_provider_id, model_id=binding.model_id,
            model_revision=binding.model_revision, model_revision_policy=binding.model_revision_policy,
            provider_protocol=binding.provider_protocol,
            effective_upstream_ids=binding.routing_constraint_snapshot.allowed_upstream_ids,
            allowed_remote_data_classes=restricted.policy.allowed_remote_data_classes,
            data_collection_policy=binding.routing_constraint_snapshot.data_collection_policy,
            require_zdr=binding.routing_constraint_snapshot.require_zdr,
            tcb_manifest_id=live.manifest_id, tcb_manifest_version=live.manifest_version,
            tcb_structure_digest=live.structure_digest, tcb_live_digest=live.live_digest,
            tcb_revision_fence=certified_tcb_revision_fence(), tcb_posture='experimental',
            full_workspace_contract_revision=binding.full_workspace_contract_revision,
            execution_family=binding.execution_family, harness_recipe_id=binding.harness_recipe_id,
            harness_recipe_revision=binding.harness_recipe_revision, harness_recipe_digest=binding.harness_recipe_digest,
            provider_capability_catalog_digest=binding.provider_capability_catalog_digest,
            semantic_projection_compiler_revision=binding.semantic_projection_compiler_revision,
            tool_contract_revision=binding.tool_contract_revision,
            context_policy_revision=binding.context_policy_snapshot.revision if binding.context_policy_snapshot else '',
            authorization_domain='certification_lab', lab_permit_reference=binding.lab_permit_reference,
            lab_permit_expires_at=permit.expires_at, lab_granted_upstream_ids=permit.routing_constraint.allowed_upstream_ids,
        )
        return replace(authority, authority_digest=canonical_digest(authority))

    def validate_candidate(self, adapter):
        permit = self.permit_store.resolve(self.ownership.reference)
        live = certified_tcb_identity()
        if (permit.candidate.adapter_artifact_digest != runtime_adapter_artifact_digest(adapter)
                or (live.manifest_id, live.manifest_version, live.structure_digest, live.live_digest)
                != (permit.candidate.tcb_manifest_id, permit.candidate.tcb_manifest_version,
                    permit.candidate.tcb_structure_digest, permit.candidate.tcb_live_digest)):
            raise LabAuthorizationError('lab_candidate_drift')
        return live

    def revalidate(self, *, session, authority):
        permit = self.validate_session(session)
        if (authority.authorization_domain != 'certification_lab' or authority.certificate_id is not None
                or authority.lab_permit_reference != self.ownership.reference
                or authority.execution_binding_id != session.execution_binding.execution_binding_id
                or authority.lab_permit_expires_at != permit.expires_at
                or authority.tcb_revision_fence != certified_tcb_revision_fence()):
            raise LabAuthorizationError('lab_authority_changed')
        return permit
