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
        definition.definition_id: definition
        for definition in provider_store.list_agentic_profile_definitions()
    }
    remote_definitions = {
        key: definition
        for key, definition in definitions.items()
        if is_remote_agentic_identity(definition)
    }
    binding_targets: list[RemoteContainmentTarget] = []
    for binding in provider_store.list_all_workspace_agentic_profile_bindings():
        definition = definitions.get(binding.definition_id)
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
                current_status="enabled" if binding.enabled else "disabled_default",
                target_status="disabled",
            )
        )

    inventory = inventory_remote_agentic_sessions(runtime_store)
    session_targets = [
        _target(
            "session",
            item.session_id,
            workspace_id=item.workspace_id,
            model_provider_id=item.model_provider_id,
            definition_id=None,
            current_status=item.session_status,
            target_status="recovery_required",
        )
        for item in inventory
        if item.quarantine_required
    ]
    for targets in (binding_targets, session_targets):
        targets.sort(key=lambda target: (target.workspace_id or "", target.identity))
    digest = canonical_digest(
        {
            "bindings": [asdict(item) for item in binding_targets],
            "sessions": [asdict(item) for item in session_targets],
            "inventory": [asdict(item) for item in inventory],
        }
    )
    return {
        "bindings": tuple(binding_targets),
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
    current_status: str,
    target_status: str,
) -> RemoteContainmentTarget:
    payload = {
        "target_kind": target_kind,
        "identity": identity,
        "workspace_id": workspace_id,
        "model_provider_id": model_provider_id,
        "definition_id": definition_id,
        "current_status": current_status,
        "target_status": target_status,
    }
    return RemoteContainmentTarget(
        **payload,
        target_digest=canonical_digest(payload),
    )
