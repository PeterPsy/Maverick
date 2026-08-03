"""Discovery and invocation helpers for app-owned reference providers."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import logging
from pathlib import Path
from threading import Lock
import time
from typing import Any

from core.api.session_api import RequestSession
from core.apps.errors import AppHostingError, WorkspaceAppBindingNotFoundError
from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.authorization.service import can_mount_app_visibility, resolve_workspace_authorization
from core.mcp.models import McpInvocationContext
from core.mcp.registry_builder import build_core_mcp_registry
from core.mcp.runner import McpRunner
from core.mcp.service import call_mcp_tool


logger = logging.getLogger(__name__)
REFERENCE_PROVIDER_DISCOVERY_TTL_SECONDS = 2.0
_REFERENCE_PROVIDER_DISCOVERY_CACHE: dict[tuple[str, str, str, str, str], tuple[float, dict[str, dict[str, Any]], list[dict[str, Any]]]] = {}
_REFERENCE_PROVIDER_DISCOVERY_CACHE_LOCK = Lock()


def visible_workspace_apps(state, *, context: RequestSession, start_path: Path) -> dict[str, dict[str, Any]]:
    """Return enabled app bindings visible to the caller, keyed by local app id."""
    visible_apps, _providers = _workspace_reference_discovery(state, context=context, start_path=start_path)
    return {app_id: dict(payload) for app_id, payload in visible_apps.items()}


def reference_providers(state, *, context: RequestSession, start_path: Path) -> list[dict[str, Any]]:
    _visible_apps, providers = _workspace_reference_discovery(state, context=context, start_path=start_path)
    return [_copy_provider(provider) for provider in providers]


def visible_workspace_apps_by_app_id(
    state,
    *,
    context: RequestSession,
    start_path: Path,
    app_ids: set[str],
) -> dict[str, dict[str, Any]]:
    """Return visible enabled app bindings for the requested local app ids only."""
    apps, _providers = _targeted_workspace_reference_discovery(
        state,
        context=context,
        start_path=start_path,
        app_ids=app_ids,
    )
    return apps


def reference_providers_by_app_id(
    state,
    *,
    context: RequestSession,
    start_path: Path,
    app_ids: set[str],
) -> dict[str, dict[str, Any]]:
    """Return reference providers for requested local app ids without workspace-wide discovery."""
    _apps, providers = _targeted_workspace_reference_discovery(
        state,
        context=context,
        start_path=start_path,
        app_ids=app_ids,
    )
    return {provider["app_id"]: provider for provider in providers}


def clear_reference_provider_discovery_cache() -> None:
    """Clear the short-lived reference provider discovery cache."""
    with _REFERENCE_PROVIDER_DISCOVERY_CACHE_LOCK:
        _REFERENCE_PROVIDER_DISCOVERY_CACHE.clear()


def _workspace_reference_discovery(
    state,
    *,
    context: RequestSession,
    start_path: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    key = _reference_discovery_cache_key(state, context=context, start_path=start_path)
    now = time.monotonic()
    with _REFERENCE_PROVIDER_DISCOVERY_CACHE_LOCK:
        cached = _REFERENCE_PROVIDER_DISCOVERY_CACHE.get(key)
        if cached is not None and cached[0] > now:
            return (
                {app_id: dict(payload) for app_id, payload in cached[1].items()},
                [_copy_provider(provider) for provider in cached[2]],
            )
    visible_apps, providers = _discover_workspace_references(state, context=context, start_path=start_path)
    expires_at = now + REFERENCE_PROVIDER_DISCOVERY_TTL_SECONDS
    with _REFERENCE_PROVIDER_DISCOVERY_CACHE_LOCK:
        _REFERENCE_PROVIDER_DISCOVERY_CACHE[key] = (
            expires_at,
            {app_id: dict(payload) for app_id, payload in visible_apps.items()},
            [_copy_provider(provider) for provider in providers],
        )
    return visible_apps, providers


def _discover_workspace_references(
    state,
    *,
    context: RequestSession,
    start_path: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    apps: dict[str, dict[str, Any]] = {}
    providers: list[dict[str, Any]] = []
    for binding in enabled_workspace_app_bindings(state.app_store, workspace_id=context.workspace_id):
        payloads = _reference_payloads_for_binding(state, binding=binding, context=context, start_path=start_path)
        if payloads is None:
            continue
        app_payload, provider = payloads
        apps[binding.app_id] = app_payload
        if provider is not None:
            providers.append(provider)
    return apps, providers


def _targeted_workspace_reference_discovery(
    state,
    *,
    context: RequestSession,
    start_path: Path,
    app_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    apps: dict[str, dict[str, Any]] = {}
    providers: list[dict[str, Any]] = []
    for app_id in sorted(item for item in app_ids if item):
        binding = _enabled_workspace_app_binding_for_reference(state, context=context, app_id=app_id)
        if binding is None:
            continue
        payloads = _reference_payloads_for_binding(state, binding=binding, context=context, start_path=start_path)
        if payloads is None:
            continue
        app_payload, provider = payloads
        apps[binding.app_id] = app_payload
        if provider is not None:
            providers.append(provider)
    return apps, providers


def _enabled_workspace_app_binding_for_reference(state, *, context: RequestSession, app_id: str):
    try:
        binding = state.app_store.get_workspace_app_binding(workspace_id=context.workspace_id, app_id=app_id)
    except WorkspaceAppBindingNotFoundError:
        binding = next(
            (
                candidate
                for candidate in enabled_workspace_app_bindings(state.app_store, workspace_id=context.workspace_id)
                if app_id in {candidate.mount_app_id or "", candidate.public_app_id or ""}
            ),
            None,
        )
    if binding is None or binding.status != "enabled":
        return None
    return binding


def _reference_payloads_for_binding(
    state,
    *,
    binding,
    context: RequestSession,
    start_path: Path,
) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
    try:
        _source_root, parsed = resolve_workspace_app_surface(state.app_store, binding=binding, start_path=start_path)
    except AppHostingError:
        return None
    except Exception:
        logger.exception("Skipping app `%s` after surface resolution failure.", binding.app_id)
        return None
    if not can_mount_app_visibility(
        state.workspace_store,
        user=context.user,
        workspace_id=context.workspace_id,
        platform_roles=parsed.contract.visibility.platform_roles,
        workspace_roles=parsed.contract.visibility.workspace_roles,
        capabilities=parsed.contract.visibility.capabilities,
    ):
        return None
    binding_fingerprint = _binding_reference_fingerprint(binding)
    app_payload = {
        "app_id": binding.app_id,
        "public_app_id": binding.public_app_id or parsed.app_id,
        "mount_app_id": binding.mount_app_id or binding.app_id,
        "name": parsed.name,
        "description": parsed.description,
        "binding_fingerprint": binding_fingerprint,
    }
    if not parsed.contract.capabilities.reference_entities:
        return app_payload, None
    tool_names = set(parsed.contract.capabilities.mcp_tools)
    provider = {
        "app_id": binding.app_id,
        "public_app_id": binding.public_app_id or parsed.app_id,
        "mount_app_id": binding.mount_app_id or binding.app_id,
        "tool_owner_app_id": binding.app_id,
        "name": parsed.name,
        "description": parsed.description,
        "binding_fingerprint": binding_fingerprint,
        "entities": [asdict(entity) for entity in parsed.contract.capabilities.reference_entities],
        "tools": {
            "manifest": _tool_by_suffix(tool_names, "_reference_manifest"),
            "search": _tool_by_suffix(tool_names, "_reference_search"),
            "resolve": _tool_by_suffix(tool_names, "_reference_resolve"),
            "summarize": _tool_by_suffix(tool_names, "_reference_summarize"),
        },
    }
    return app_payload, provider


def _binding_reference_fingerprint(binding) -> str:
    raw = "|".join(
        (
            binding.app_id,
            binding.public_app_id or "",
            binding.mount_app_id or "",
            binding.source_record_id,
            binding.status,
            binding.active_version,
            binding.updated_at,
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def public_provider_payload(provider: dict[str, Any]) -> dict[str, Any]:
    return {
        "app_id": provider["app_id"],
        "public_app_id": provider.get("public_app_id") or provider["app_id"],
        "mount_app_id": provider.get("mount_app_id") or provider["app_id"],
        "name": provider["name"],
        "description": provider["description"],
        "entity_types": provider["entities"],
    }


def _copy_provider(provider: dict[str, Any]) -> dict[str, Any]:
    copied = dict(provider)
    copied["entities"] = [dict(entity) for entity in provider.get("entities", []) if isinstance(entity, dict)]
    copied["tools"] = dict(provider.get("tools") if isinstance(provider.get("tools"), dict) else {})
    return copied


def _reference_discovery_cache_key(
    state,
    *,
    context: RequestSession,
    start_path: Path,
) -> tuple[str, str, str, str, str]:
    try:
        root_key = str(start_path.resolve())
    except OSError:
        root_key = str(start_path)
    binding_fingerprint = "|".join(
        ":".join(
            (
                binding.app_id,
                binding.source_record_id,
                binding.status,
                binding.active_version,
                binding.updated_at,
            )
        )
        for binding in enabled_workspace_app_bindings(state.app_store, workspace_id=context.workspace_id)
    )
    return (
        root_key,
        context.workspace_id,
        context.user.user_id,
        context.user.platform_role,
        binding_fingerprint,
    )


def call_reference_tool(
    state,
    provider: dict[str, Any],
    action: str,
    *,
    context: McpInvocationContext,
    arguments: dict[str, Any],
    start_path: Path,
    runner: McpRunner | None = None,
) -> dict[str, Any]:
    tool = str(provider["tools"].get(action) or "")
    if not tool:
        return {}
    tool_name = f"app.{provider['tool_owner_app_id']}.{tool}"
    if runner is not None:
        return runner.call_tool(tool_name=tool_name, context=context, arguments=arguments)
    return call_mcp_tool(
        tool_name=tool_name,
        context=context,
        app_store=state.app_store,
        workspace_store=state.workspace_store,
        runtime_store=state.runtime_store,
        provider_store=state.provider_store,
        secret_store=state.secret_store,
        recovery_store=state.recovery_store,
        observability_store=state.observability_store,
        app_event_bus=state.app_event_bus,
        workspace_id=context.workspace_id,
        start_path=start_path,
        arguments=arguments,
    )


def reference_tool_runner(state, *, context: McpInvocationContext, start_path: Path) -> McpRunner:
    """Build one MCP runner for a reference request path."""
    registry = build_core_mcp_registry(
        app_store=state.app_store,
        workspace_store=state.workspace_store,
        runtime_store=state.runtime_store,
        provider_store=state.provider_store,
        secret_store=state.secret_store,
        recovery_store=state.recovery_store,
        observability_store=state.observability_store,
        app_event_bus=state.app_event_bus,
        workspace_id=context.workspace_id,
        context=context,
        start_path=start_path,
    )
    return McpRunner(registry)


def mcp_context_for_request(state, context: RequestSession) -> McpInvocationContext:
    authorization = resolve_workspace_authorization(state.workspace_store, user=context.user, workspace_id=context.workspace_id)
    workspace_role = authorization.membership.role if authorization.membership and authorization.membership.status == "active" else None
    if workspace_role is None and context.user.platform_role == "admin":
        workspace_role = "admin"
    return McpInvocationContext(
        caller_kind="sandbox_agent",
        workspace_id=context.workspace_id,
        agent_id=None,
        effective_mode="sandbox",
        platform_role=context.user.platform_role,
        user_id=context.user.user_id,
        workspace_role=workspace_role,
        entrypoint_surface="reference",
    )


def _tool_by_suffix(tool_names: set[str], suffix: str) -> str:
    return next((tool_name for tool_name in sorted(tool_names) if tool_name.endswith(suffix)), "")
