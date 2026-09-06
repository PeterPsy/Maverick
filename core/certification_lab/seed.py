"""Operator preparation of a synthetic private workspace, before permit issue."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from core.certification_lab.bootstrap import open_lab_store_state
from core.certification_lab.errors import LabAuthorizationError
from core.identity.models import UserRecord
from core.providers.agentic_models import ActorSelectionPolicy, WorkspaceAgenticProfileBinding
from core.providers.provider_credentials import build_provider_credential_binding
from core.runtime.public_content_authority_store import issue_runtime_public_content_authority
from core.secrets.service import create_platform_secret
from core.workspaces.data_governance import issue_fake_data_attestation
from core.workspaces.service import (
    build_workspace_membership, build_workspace_record, default_workspace_governance,
    default_workspace_quota, ensure_workspace_layout,
)


def seed_lab_installation(layout, *, vault_key_path: Path, actor_id: str, operator_id: str,
                          provider_id: str, credential_binding_id: str, credential_value: str):
    """Explicit imported credential only; nothing is read from the caller shell.

    This operator function is not registered in CLI/MCP or the model catalog.
    It cannot mint permits, collect successful observations or publish evidence.
    """
    state = open_lab_store_state(layout, vault_key_path=vault_key_path)
    workspace_id = layout.workspace_root.name
    if state.workspace_store.list_workspaces() or state.identity_store.list_users():
        raise LabAuthorizationError('lab_seed_already_exists')
    if actor_id == operator_id:
        raise LabAuthorizationError('lab_actor_denied')
    now = datetime.now(UTC)
    ensure_workspace_layout(workspace_id, start_path=layout.repository_root)
    state.workspace_store.save_workspace(build_workspace_record(workspace_id=workspace_id, name='Synthetic laboratory',
                                                                 slug=workspace_id, created_by_user_id=operator_id, now=now))
    state.identity_store.save_user(UserRecord(actor_id, actor_id, None, 'Lab member', 'standard', 'member', True, now, now))
    state.identity_store.save_user(UserRecord(operator_id, operator_id, None, 'Lab operator', 'standard', 'member', True, now, now))
    state.workspace_store.save_membership(build_workspace_membership(membership_id='lab-membership', workspace_id=workspace_id,
                                                                      user_id=actor_id, role='member', now=now))
    state.workspace_store.save_membership(build_workspace_membership(membership_id='lab-operator-membership', workspace_id=workspace_id,
                                                                      user_id=operator_id, role='admin', now=now))
    state.workspace_store.save_governance(replace(default_workspace_governance(workspace_id, now=now),
                                                   allow_app_installation=False, allow_agent_creation=False,
                                                   allow_agent_management=False, allow_custom_apps=False,
                                                   allow_full_access_runtime=True))
    state.workspace_store.save_quota(default_workspace_quota(workspace_id, now=now))
    attestation = issue_fake_data_attestation(workspace_id=workspace_id, actor_id=operator_id, actor_kind='operator', scope_type='workspace')
    state.workspace_store.save_data_attestation(attestation, expected_revision=0)
    issue_runtime_public_content_authority(state.workspace_store, workspace_id=workspace_id, actor_id=operator_id, expected_revision=0)
    # Definitions are real production onboarding records; no certificate is
    # fabricated or migrated in order to seed the laboratory.
    for definition in state.provider_registry.list_provider_definitions():
        state.provider_store.save_provider_definition(definition)
    catalog = state.maverick_agent_onboarding_catalog
    catalog.publish_profiles(state.provider_store, now=now)
    publication = next(p for p in catalog.publications() if p.profile.model_provider_id == provider_id)
    secret = create_platform_secret(state.secret_store, label='Lab provider credential', secret_id='lab-provider', raw_value=credential_value)
    credential = build_provider_credential_binding(binding_id=credential_binding_id, provider_id=provider_id,
                                                    workspace_id=workspace_id, secret_ref=f'platform:secrets/{secret.secret_id}')
    state.provider_store.save_provider_binding(credential)
    profile = publication.profile
    binding = WorkspaceAgenticProfileBinding(
        binding_id='lab-workspace-binding', workspace_id=workspace_id, definition_id=profile.definition_id,
        definition_revision=profile.revision, credential_binding_id=credential_binding_id,
        enabled=True, is_default=False, actor_policy=ActorSelectionPolicy(False, (actor_id,), (), ()),
        workspace_policy_ceiling=profile.policy_ceiling, egress_policy_id=profile.egress_policy_id,
        egress_policy_revision=profile.egress_policy_revision, revision=1, created_at=now, updated_at=now,
    )
    state.provider_store.save_workspace_agentic_profile_binding(binding, expected_revision=None)
    return state, publication, credential, binding, attestation
