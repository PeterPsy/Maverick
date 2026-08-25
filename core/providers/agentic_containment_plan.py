"""Read-only planner for Phase-0 remote agentic containment."""

from __future__ import annotations

from dataclasses import asdict

from core.providers.agentic_containment_models import RemoteContainmentTarget
from core.providers.store import ProviderStore
from core.runtime.agentic_inventory import inventory_remote_agentic_sessions
from core.runtime.execution_binding import canonical_digest
from core.runtime.remote_agentic_admission import is_remote_agentic_identity
from core.runtime.store import RuntimeStore


def build_remote_agentic_containment_plan(
    provider_store: ProviderStore,
    runtime_store: RuntimeStore,
) -> dict:
    """Build one deterministic plan without mutating either store."""
    definitions = {
        (definition.definition_id, definition.revision): definition
        for definition in provider_store.list_agentic_profile_definitions()
    }
    remote_definitions = {
        key: definition
        for key, definition in definitions.items()
        if is_remote_agentic_identity(definition)
    }
    binding_targets: list[RemoteContainmentTarget] = []
    for binding in provider_store.list_all_workspace_agentic_profile_bindings():
        key = (binding.definition_id, binding.definition_revision)
        definition = definitions.get(key)
        if definition is not None and not is_remote_agentic_identity(definition):
            continue
        if not binding.enabled and not binding.is_default:
            continue
        binding_targets.append(
            _target(
                "binding",
                binding.binding_id,
                workspace_id=binding.workspace_id,
                model_provider_id=(
                    "unknown" if definition is None else definition.model_provider_id
                ),
                definition_id=binding.definition_id,
                definition_revision=binding.definition_revision,
                current_revision=binding.revision,
                current_status="enabled" if binding.enabled else "disabled_default",
                target_status="disabled",
            )
        )

    profile_targets: list[RemoteContainmentTarget] = []
    for key, definition in remote_definitions.items():
        status = provider_store.get_agentic_profile_definition_status(*key)
        if status is not None and status.rollout_status in {"disabled", "suspended"}:
            continue
        profile_targets.append(
            _target(
                "profile",
                f"{definition.definition_id}:{definition.revision}",
                workspace_id=None,
                model_provider_id=definition.model_provider_id,
                definition_id=definition.definition_id,
                definition_revision=definition.revision,
                current_revision=None if status is None else status.revision,
                current_status="missing_status" if status is None else status.rollout_status,
                target_status="suspended",
            )
        )

    certificate_targets: list[RemoteContainmentTarget] = []
    for certificate in provider_store.list_capability_certificates():
        if certificate.suite_version != "8" or not is_remote_agentic_identity(certificate):
            continue
        status = provider_store.get_capability_certificate_status(certificate.certificate_id)
        if status is not None and status.status == "revoked":
            continue
        certificate_targets.append(
            _target(
                "certificate",
                certificate.certificate_id,
                workspace_id=None,
                model_provider_id=certificate.model_provider_id,
                definition_id=None,
                definition_revision=None,
                current_revision=None if status is None else status.revision,
                current_status="missing_status" if status is None else status.status,
                target_status="revoked",
            )
        )

    inventory = inventory_remote_agentic_sessions(runtime_store)
    session_targets = [
        _target(
            "session",
            item.session_id,
            workspace_id=item.workspace_id,
            model_provider_id=item.model_provider_id,
            definition_id=item.profile_definition_id,
            definition_revision=item.profile_definition_revision,
            current_revision=None,
            current_status=item.session_status,
            target_status="recovery_required",
        )
        for item in inventory
        if item.quarantine_required
    ]
    for targets in (binding_targets, profile_targets, certificate_targets, session_targets):
        targets.sort(key=lambda target: (target.workspace_id or "", target.identity))
    digest = canonical_digest(
        {
            "bindings": [asdict(item) for item in binding_targets],
            "profiles": [asdict(item) for item in profile_targets],
            "certificates": [asdict(item) for item in certificate_targets],
            "sessions": [asdict(item) for item in session_targets],
            "inventory": [asdict(item) for item in inventory],
        }
    )
    return {
        "bindings": tuple(binding_targets),
        "profiles": tuple(profile_targets),
        "certificates": tuple(certificate_targets),
        "sessions": tuple(session_targets),
        "inventory": inventory,
        "digest": digest,
    }


def _target(
    target_kind,
    identity: str,
    *,
    workspace_id: str | None,
    model_provider_id: str,
    definition_id: str | None,
    definition_revision: str | None,
    current_revision: int | None,
    current_status: str,
    target_status: str,
) -> RemoteContainmentTarget:
    payload = {
        "target_kind": target_kind,
        "identity": identity,
        "workspace_id": workspace_id,
        "model_provider_id": model_provider_id,
        "definition_id": definition_id,
        "definition_revision": definition_revision,
        "current_revision": current_revision,
        "current_status": current_status,
        "target_status": target_status,
    }
    return RemoteContainmentTarget(
        **payload,
        target_digest=canonical_digest(payload),
    )
