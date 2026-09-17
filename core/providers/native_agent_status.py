"""Redaction-safe status projection for registered native-agent runtimes."""

from __future__ import annotations

from pathlib import Path

from core.providers.errors import ProviderNotFoundError
from core.providers.execution_families import NATIVE_AGENT_EXECUTION_FAMILY
from core.providers.native_agent_catalog import native_agent_catalog_models
from core.providers.native_agent_contract import NativeRuntimeStatus


def native_agent_status_items(registry, *, store=None) -> list[dict[str, object]]:
    """Inspect every native registration without exposing host paths or secrets."""
    items = [
        _native_agent_status_item(registry, installation, store=store)
        for installation in registry.list_native_agent_installations()
    ]
    items.sort(
        key=lambda item: (
            str(item["runtime_engine_id"]) != "codex",
            str(item["label"]),
        )
    )
    return items


def _native_agent_status_item(registry, installation, *, store) -> dict[str, object]:
    manifest = installation.manifest
    try:
        definition = registry.get_provider_definition(manifest.runtime_engine_id)
    except ProviderNotFoundError:
        definition = None
    try:
        status = installation.inspector.inspect()
    except Exception:
        status = NativeRuntimeStatus(
            availability="unknown",
            executable_path=None,
            runtime_version=None,
            health="unavailable",
            reason_codes=("runtime_inspection_failed",),
            update_status="unknown",
        )
    contract_complete = bool(
        installation.effects.workspace_confined
        and installation.effects.process_tree_supervised
        and installation.effects.structured_effect_events
    )
    runtime_ready = status.availability == "installed" and status.health == "healthy"
    enabled = bool(definition is not None and definition.status == "active")
    selectable = contract_complete and runtime_ready and enabled
    unavailable_reason = native_runtime_unavailable_reason(
        contract_complete=contract_complete,
        runtime_ready=runtime_ready,
        enabled=enabled,
        status=status,
    )
    catalog_models = native_agent_catalog_models(registry, installation)
    return {
        "runtime_engine_id": manifest.runtime_engine_id,
        "label": manifest.runtime_engine_id if definition is None else definition.label,
        "description": "" if definition is None else definition.description,
        "execution_family": NATIVE_AGENT_EXECUTION_FAMILY,
        "provider_status": "missing" if definition is None else definition.status,
        "availability": status.availability,
        "installed": status.availability == "installed",
        "executable_name": (
            None if status.executable_path is None else Path(status.executable_path).name
        ),
        "runtime_version": status.runtime_version,
        "health": status.health,
        "health_reason_codes": status.reason_codes,
        "update": {
            "status": status.update_status,
            "detail": status.update_detail,
        },
        "adapter": {
            "id": manifest.adapter_id,
            "version": manifest.adapter_version,
            "trusted_distribution": manifest.trusted_distribution,
        },
        "protocol": {
            "kind": manifest.protocol_kind,
            "id": manifest.protocol_id,
            "version": manifest.protocol_version,
            "event_schema": manifest.structured_event_schema,
        },
        "authentication_status": (
            "runtime_managed"
            if installation.contract_configured
            else "not_configured"
        ),
        "models": [
            {
                "provider_id": model.model_provider_id,
                "model_id": model.model_id,
                "model_revision": model.model_revision,
                "model_revision_policy": model.revision_policy,
            }
            for model in catalog_models
        ],
        "effects": {
            "mode": installation.effects.mode,
            "workspace_confined": installation.effects.workspace_confined,
            "process_tree_supervised": installation.effects.process_tree_supervised,
            "structured_effect_events": installation.effects.structured_effect_events,
            "sandbox_policy_revision": installation.effects.sandbox_policy_revision,
            "approval_policy": installation.effects.approval_policy,
        },
        "contract_state": "available" if contract_complete else "unavailable",
        "selectable": selectable,
        "unavailable_reason": unavailable_reason,
    }


def native_runtime_unavailable_reason(
    *,
    contract_complete,
    runtime_ready,
    enabled,
    status,
) -> str | None:
    if not contract_complete:
        return "native_agent_contract_incomplete"
    if status.availability == "not_installed":
        return "native_runtime_not_installed"
    if status.availability != "installed":
        return (
            status.reason_codes[0]
            if status.reason_codes
            else "native_runtime_availability_unknown"
        )
    if not runtime_ready:
        return (
            status.reason_codes[0]
            if status.reason_codes
            else "native_runtime_unhealthy"
        )
    if not enabled:
        return "native_agent_disabled"
    return None


__all__ = ["native_agent_status_items", "native_runtime_unavailable_reason"]
