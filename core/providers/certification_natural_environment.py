"""Disposable installation and permit setup for OpenRouter natural certification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import secrets

from cryptography.hazmat.primitives.serialization import load_pem_private_key
from core.api.platform_state import bootstrap_platform_state
from core.identity.service import build_user_record
from core.providers.agentic_models import (
    WorkspaceAgenticProfileBinding,
    default_actor_selection_policy,
)
from core.providers.certificate_service import runtime_adapter_artifact_digest
from core.providers.certification_budget_ledger import CertificationBudgetLedger
from core.providers.certification_natural_artifacts import (
    OpenRouterNaturalOperatorConfig,
    jsonable,
    write_new_json,
)
from core.providers.certification_natural_fixtures import (
    materialize_openrouter_natural_fixtures,
)
from core.providers.certification_natural_lab import (
    CertificationNaturalLabAuthority,
    CertificationNaturalLabPermit,
    build_certification_natural_runtime_registry,
    directory_identity,
    sign_certification_natural_lab_permit,
)
from core.providers.certification_target import api_profile_target_digest
from core.providers.certified_execution_tcb import certified_tcb_identity
from core.providers.openrouter_agentic_profile import (
    OPENROUTER_AGENTIC_PROFILE_ID,
    OPENROUTER_AGENTIC_PROFILE_REVISION,
)
from core.providers.provider_credentials import bind_provider_credential
from core.runtime.execution_binding import canonical_digest
from core.runtime.hosted_agentic_factory import build_hosted_agentic_engine_adapter
from core.secrets.service import build_secret_ref, create_platform_secret
from core.workspaces.service import (
    ensure_default_workspace_record,
    ensure_workspace_layout,
    ensure_workspace_membership,
    set_active_workspace_for_user,
)

PROFILE = (
    OPENROUTER_AGENTIC_PROFILE_ID,
    OPENROUTER_AGENTIC_PROFILE_REVISION,
    ("max", "high", "low"),
)


def configure_environment(run_root: Path) -> None:
    control = run_root / "control"
    home = run_root / "home"
    control.mkdir(mode=0o700)
    home.mkdir(mode=0o700)
    key = run_root / "secret-store.key"
    key.write_text(secrets.token_hex(32) + "\n", encoding="utf-8")
    os.chmod(key, 0o600)
    os.environ.update({
        "HOME": str(home),
        "MAVERICK_CONTROL_STORE": "json",
        "MAVERICK_JSON_CONTROL_STORE_ROOT": str(control),
        "MAVERICK_LOCAL_STATE_ROOT": str(run_root / "local-state"),
        "MAVERICK_SECRET_KEY_FILE": str(key),
        "MAVERICK_FEATURE_AGENTIC_PROFILES": "1",
        "MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT": "1",
        "MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME": "1",
        "MAVERICK_FEATURE_AGENTIC_TOOL_CONFIRMATION": "1",
        "MAVERICK_FEATURE_PROVIDER_PRIVATE_STATE": "1",
        "MAVERICK_FEATURE_AGENTIC_EGRESS_ENFORCEMENT": "1",
        "MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW": "0",
        "MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW": "1",
        "MAVERICK_FEATURE_ANTIGRAVITY_AGENTIC_PREVIEW": "0",
        "MAVERICK_FEATURE_PARALLEL_TOOL_CALLS": "0",
    })


def bootstrap(
    config: OpenRouterNaturalOperatorConfig,
    effort: str,
    raw_credential: str,
    run_root: Path,
):
    state = bootstrap_platform_state(
        start_path=config.repository_root,
        install_builtin_apps=True,
        bootstrap_admin=False,
    )
    actor_id = "user:natural-certification"
    state.identity_store.save_user(
        build_user_record(
            user_id=actor_id,
            username="natural-certification",
            display_name="Natural Certification Operator",
            platform_role="admin",
        )
    )
    workspace_record = ensure_default_workspace_record(state.workspace_store)
    ensure_workspace_membership(
        state.workspace_store,
        membership_id=f"default:{actor_id}",
        workspace_id="default",
        user_id=actor_id,
        role="admin",
    )
    set_active_workspace_for_user(
        state.workspace_store,
        user_id=actor_id,
        workspace_id="default",
    )
    governance = state.workspace_store.get_governance(workspace_record.workspace_id)
    if not governance.allow_full_access_runtime:
        raise RuntimeError("natural_default_workspace_full_access_disabled")
    paths = ensure_workspace_layout(
        workspace_record.workspace_id,
        start_path=config.repository_root,
    )
    skill = materialize_openrouter_natural_fixtures(paths.root)
    secret = create_platform_secret(
        state.secret_store,
        label="Natural OpenRouter credential",
        raw_value=raw_credential,
        alias=f"natural-openrouter-{effort}",
        secret_id=f"natural-openrouter-{effort}",
        kind="api_key",
    )
    credential_binding = bind_provider_credential(
        state.provider_store,
        provider_id="openrouter",
        workspace_id=workspace_record.workspace_id,
        secret_ref=build_secret_ref(secret_id=secret.secret_id),
        binding_id=f"natural-credential-openrouter-{effort}",
    )
    definition = state.provider_store.get_agentic_profile_definition(*PROFILE[:2])
    timestamp = datetime.now(tz=UTC)
    workspace_binding = WorkspaceAgenticProfileBinding(
        binding_id=f"natural-profile-openrouter-{effort}",
        workspace_id=workspace_record.workspace_id,
        definition_id=definition.definition_id,
        definition_revision=definition.revision,
        credential_binding_id=credential_binding.binding_id,
        enabled=True,
        is_default=True,
        actor_policy=default_actor_selection_policy(),
        workspace_policy_ceiling=definition.policy_ceiling,
        egress_policy_id=definition.egress_policy_id,
        egress_policy_revision=definition.egress_policy_revision,
        revision=0,
        created_at=timestamp,
        updated_at=timestamp,
        admission_enabled_at=timestamp,
    )
    state.provider_store.save_workspace_agentic_profile_binding(
        workspace_binding,
        expected_revision=None,
    )
    write_new_json(
        run_root / "setup.json",
        {
            "workspace_id": workspace_record.workspace_id,
            "actor_id": actor_id,
            "skill": jsonable(skill),
        },
    )
    return (
        state,
        actor_id,
        workspace_record,
        workspace_binding,
        credential_binding,
        definition,
        skill,
    )


def build_permit(
    config: OpenRouterNaturalOperatorConfig,
    state,
    actor_id,
    workspace_record,
    workspace_binding,
    credential_binding,
    definition,
    effort,
    run_id,
    issued_at,
    run_root,
):
    workspace_root = config.repository_root / "workspaces" / workspace_record.workspace_id
    tcb = certified_tcb_identity(config.repository_root)
    production_adapter = state.provider_registry.get_agentic_runtime_adapter(
        "maverick-tool-loop"
    )
    adapter_digest = runtime_adapter_artifact_digest(production_adapter)
    ledger = CertificationBudgetLedger(
        config.ledger_path,
        policy_digest=config.ledger_policy_digest,
    )
    permit = CertificationNaturalLabPermit(
        schema="maverick-certification-natural-lab-permit.v1",
        permit_id=f"permit-{run_id}",
        authorization_ref=ledger.authorization_ref,
        source_commit=config.source_commit,
        repository_root_identity=directory_identity(config.repository_root),
        target_digest=api_profile_target_digest(definition),
        adapter_artifact_digest=adapter_digest,
        tcb_manifest_id=tcb.manifest_id,
        tcb_manifest_version=tcb.manifest_version,
        tcb_structure_digest=tcb.structure_digest,
        tcb_live_digest=tcb.live_digest,
        workspace_id=workspace_record.workspace_id,
        workspace_root=str(workspace_root),
        workspace_root_identity=directory_identity(workspace_root),
        actor_user_id=actor_id,
        definition_id=definition.definition_id,
        definition_revision=definition.revision,
        workspace_binding_id=workspace_binding.binding_id,
        credential_binding_digest=canonical_digest(credential_binding),
        reasoning_effort=effort,
        ledger_policy_digest=ledger.policy_digest,
        run_id=run_id,
        reviewer_ref=config.reviewer_ref,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(hours=20),
    )
    key = load_pem_private_key(config.signer_key_path.read_bytes(), password=None)
    signed = sign_certification_natural_lab_permit(
        permit,
        signer_key_id=config.signer_key_id,
        private_key=key,
    )
    public = key.public_key()
    write_new_json(
        run_root / "permit.json",
        {
            "permit": jsonable(permit),
            "signer_key_id": signed.signer_key_id,
            "signature": signed.signature,
        },
    )
    authority = CertificationNaturalLabAuthority(
        signed_permit=signed,
        trusted_keys={config.signer_key_id: public},
        state=state,
        ledger=ledger,
        credential_fingerprint_key=secrets.token_bytes(32),
    )
    runtime_registry = build_certification_natural_runtime_registry(authority)
    adapter = build_hosted_agentic_engine_adapter(
        state,
        provider_registry=state.provider_registry,
        onboarding_catalog=state.maverick_agent_onboarding_catalog,
        certification_lab_authority=authority,
        certification_lab_runtime_registry=runtime_registry,
    )
    if runtime_adapter_artifact_digest(adapter) != adapter_digest:
        raise RuntimeError("natural_lab_adapter_digest_mismatch")
    return signed, authority, adapter, ledger, production_adapter.adapter_version

__all__ = [
    "PROFILE",
    "bootstrap",
    "build_permit",
    "configure_environment",
]
