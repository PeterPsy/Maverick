"""Discovery and invocation helpers for app-owned reference providers."""

from __future__ import annotations

from dataclasses import asdict
import logging
from pathlib import Path
from typing import Any

from core.api.session_api import RequestSession
from core.apps.errors import AppHostingError
from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.authorization.service import can_mount_app_visibility, resolve_workspace_authorization
from core.mcp.models import McpInvocationContext
from core.mcp.registry_builder import build_core_mcp_registry
from core.mcp.runner import McpRunner
from core.mcp.service import call_mcp_tool


logger = logging.getLogger(__name__)


def visible_workspace_apps(state, *, context: RequestSession, start_path: Path) -> dict[str, dict[str, Any]]:
    """Return enabled app bindings visible to the caller, keyed by local app id."""
    apps: dict[str, dict[str, Any]] = {}
    for binding in enabled_workspace_app_bindings(state.app_store, workspace_id=context.workspace_id):
        try:
            _source_root, parsed = resolve_workspace_app_surface(state.app_store, binding=binding, start_path=start_path)
        except AppHostingError:
            continue
        except Exception:
            logger.exception("Skipping app `%s` after surface resolution failure.", binding.app_id)
            continue
        if not can_mount_app_visibility(
            state.workspace_store,
            user=context.user,
            workspace_id=context.workspace_id,
            platform_roles=parsed.contract.visibility.platform_roles,
            workspace_roles=parsed.contract.visibility.workspace_roles,
            capabilities=parsed.contract.visibility.capabilities,
        ):
            continue
        apps[binding.app_id] = {
            "app_id": binding.app_id,
            "public_app_id": binding.public_app_id or parsed.app_id,
            "mount_app_id": binding.mount_app_id or binding.app_id,
            "name": parsed.name,
            "description": parsed.description,
        }
    return apps


def reference_providers(state, *, context: RequestSession, start_path: Path) -> list[dict[str, Any]]:
    providers: list[dict[str, Any]] = []
    for binding in enabled_workspace_app_bindings(state.app_store, workspace_id=context.workspace_id):
        try:
            _source_root, parsed = resolve_workspace_app_surface(state.app_store, binding=binding, start_path=start_path)
        except AppHostingError:
            continue
        except Exception:
            logger.exception("Skipping app `%s` reference provider after surface resolution failure.", binding.app_id)
            continue
        if not parsed.contract.capabilities.reference_entities:
            continue
        if not can_mount_app_visibility(
            state.workspace_store,
            user=context.user,
            workspace_id=context.workspace_id,
            platform_roles=parsed.contract.visibility.platform_roles,
            workspace_roles=parsed.contract.visibility.workspace_roles,
            capabilities=parsed.contract.visibility.capabilities,
        ):
            continue
        tool_names = set(parsed.contract.capabilities.mcp_tools)
        providers.append(
            {
                "app_id": binding.app_id,
                "public_app_id": binding.public_app_id or parsed.app_id,
                "mount_app_id": binding.mount_app_id or binding.app_id,
                "tool_owner_app_id": binding.app_id,
                "name": parsed.name,
                "description": parsed.description,
                "entities": [asdict(entity) for entity in parsed.contract.capabilities.reference_entities],
                "tools": {
                    "manifest": _tool_by_suffix(tool_names, "_reference_manifest"),
                    "search": _tool_by_suffix(tool_names, "_reference_search"),
                    "resolve": _tool_by_suffix(tool_names, "_reference_resolve"),
                    "summarize": _tool_by_suffix(tool_names, "_reference_summarize"),
                },
            }
        )
    return providers


def public_provider_payload(provider: dict[str, Any]) -> dict[str, Any]:
    return {
        "app_id": provider["app_id"],
        "public_app_id": provider.get("public_app_id") or provider["app_id"],
        "mount_app_id": provider.get("mount_app_id") or provider["app_id"],
        "name": provider["name"],
        "description": provider["description"],
        "entity_types": provider["entities"],
    }


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
    )


def _tool_by_suffix(tool_names: set[str], suffix: str) -> str:
    return next((tool_name for tool_name in sorted(tool_names) if tool_name.endswith(suffix)), "")
