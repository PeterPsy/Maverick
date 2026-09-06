"""Private laboratory composition; never call the active platform bootstrap."""

from dataclasses import replace
import os
from pathlib import Path

from core.api.control_store import ControlStoreSettings
from core.api.platform_store_composition import compose_platform_store_state
from core.certification_lab.authority import LabRuntimeAuthorization
from core.certification_lab.errors import LabAuthorizationError
from core.certification_lab.evidence import LabEvidenceRecorder
from core.certification_lab.execution_binding import build_lab_execution_binding
from core.certification_lab.private_files import read_private_file
from core.runtime.agentic_feature_flags import (
    MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT, MAVERICK_FEATURE_AGENTIC_EGRESS_ENFORCEMENT,
    MAVERICK_FEATURE_AGENTIC_PROFILES, MAVERICK_FEATURE_AGENTIC_TOOL_CONFIRMATION,
    MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW, MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
    MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW, MAVERICK_FEATURE_PROVIDER_PRIVATE_STATE,
)
from core.runtime.hosted_agentic_factory import build_hosted_agentic_engine_adapter
from core.runtime.runtime_session import RuntimeSessionRecord
from core.secrets.key_material import secret_store_key_id
from core.secrets.store import SecretCollections
from core.shared.json_file_collection import JsonFileCollection


def lab_process_environment(layout) -> dict[str, str]:
    """An allowlist built from scratch, not os.environ with a few overrides."""
    result = {
        'PATH': '/usr/bin:/bin', 'HOME': str(layout.operator_root / 'home'),
        'LANG': 'C.UTF-8', 'PYTHONPATH': str(layout.repository_root), 'PYTHONDONTWRITEBYTECODE': '1',
    }
    for name in (MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT, MAVERICK_FEATURE_AGENTIC_EGRESS_ENFORCEMENT,
                 MAVERICK_FEATURE_AGENTIC_PROFILES, MAVERICK_FEATURE_AGENTIC_TOOL_CONFIRMATION,
                 MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW, MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
                 MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW, MAVERICK_FEATURE_PROVIDER_PRIVATE_STATE):
        result[name] = '1'
    return result


def open_lab_store_state(layout, *, vault_key_path: Path):
    layout.validate()
    if Path(__file__).resolve().parents[2] != layout.repository_root:
        raise LabAuthorizationError('lab_loaded_source_mismatch')
    if dict(os.environ) != lab_process_environment(layout):
        raise LabAuthorizationError('lab_ambient_environment_forbidden')
    if vault_key_path.parent != layout.vault_root:
        raise LabAuthorizationError('lab_vault_identity_mismatch')

    def key_loader():
        value = read_private_file(vault_key_path, max_bytes=32)
        if len(value) != 32:
            raise LabAuthorizationError('lab_vault_key_invalid')
        return value

    def keyring_loader():
        key = key_loader()
        return {secret_store_key_id(key): key}

    key_loader()
    collections = SecretCollections(**{
        name: JsonFileCollection(layout.vault_root / f'{name}.json')
        for name in ('secrets', 'values', 'bindings', 'grants')
    })
    return compose_platform_store_state(
        repository_root=layout.repository_root,
        control_settings=ControlStoreSettings(kind='json', json_root=layout.control_root),
        key_loader=key_loader, keyring_loader=keyring_loader, secret_collections=collections,
    )


def bootstrap_lab_worker(layout, *, vault_key_path, permit_store, reference, ledger,
                         session_id, scenario_id, workspace_binding_id, reasoning_effort):
    """Open prepared private state; restart neither creates nor renews grants."""
    state = open_lab_store_state(layout, vault_key_path=vault_key_path)
    if (permit_store.path.parent != layout.operator_root
            or permit_store.trust.path.parent != layout.operator_root
            or ledger.path.parent != layout.operator_root):
        raise LabAuthorizationError('lab_operator_store_identity_mismatch')
    permit = permit_store.resolve(reference)
    if (permit.installation_id != layout.installation_id or permit.candidate.source_commit != layout.source_commit
            or permit.workspace.root_path != str(layout.workspace_root)):
        raise LabAuthorizationError('lab_installation_mismatch')
    # Native grants remain distinctly representable but not executable through
    # this API-engine vertical. A native worker must validate its binary/effects.
    if permit.target.scope != 'api_profile':
        raise LabAuthorizationError('lab_native_worker_required')
    ownership = permit_store.claim(reference, session_id=session_id, scenario_id=scenario_id)
    definition = state.provider_store.get_agentic_profile_definition(permit.target.definition_id, permit.target.definition_revision)
    workspace_binding = state.provider_store.get_workspace_agentic_profile_binding(workspace_binding_id)
    binding = build_lab_execution_binding(permit_store, ownership=ownership, definition=definition,
                                           workspace_binding=workspace_binding, reasoning_effort=reasoning_effort)
    authorization = LabRuntimeAuthorization(permit_store, ownership, state.workspace_store, state.provider_store,
                                            state.runtime_store, ledger, layout.repository_root, layout.source_commit,
                                            LabEvidenceRecorder(layout.operator_root, session_id=session_id))
    state = replace(state, lab_runtime_authorization=authorization)
    # Validate exact attestation/root/credential/ledger before any session write.
    authorization.validate_binding(binding)
    from core.runtime.runtime_actor import resolve_runtime_actor_roles

    role, actor, workspace_role = resolve_runtime_actor_roles(state, user_id=permit.workspace.actor_id,
                                                              workspace_id=permit.workspace.workspace_id)
    if role != 'member' or workspace_role != 'member' or actor != permit.workspace.actor_id:
        raise LabAuthorizationError('lab_actor_denied')
    session = RuntimeSessionRecord(
        session_id=session_id, workspace_id=binding.workspace_id, agent_id='certification-lab',
        status='created', requested_mode='full-access', effective_mode='full-access', preparation_status='unprepared',
        workspace_root=str(layout.workspace_root), workdir=str(layout.workspace_root),
        runtime_root=str(layout.workspace_root / 'runtime'), started_at=None, updated_at=binding.created_at,
        ended_at=None, last_progress_at=None, execution_binding=binding,
        owner_user_id=permit.workspace.actor_id, created_by_user_id=permit.workspace.actor_id,
        authorization_domain='certification_lab', lab_installation_id=permit.installation_id,
    )
    adapter = build_hosted_agentic_engine_adapter(state, provider_registry=state.provider_registry,
                                                 onboarding_catalog=state.maverick_agent_onboarding_catalog)
    authorization.validate_candidate(adapter)
    from core.runtime.session_preparation import prepare_runtime_session

    session, _published = prepare_runtime_session(state.runtime_store, session, binding, now=binding.created_at)
    return state, session, adapter
