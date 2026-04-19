"""Recovery-oriented core MCP tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.apps.store import AppStore
from core.mcp.core_tool_helpers import OPERATOR_ONLY, core_mcp_tool
from core.mcp.models import McpInvocationContext, McpToolDefinition
from core.providers.provider_registry import ProviderRegistry
from core.recovery.service import execute_session_restart, record_app_health, record_failed_start, record_provider_health, record_runtime_health, recovery_status
from core.recovery.store import RecoveryStore
from core.runtime.store import RuntimeStore


def recovery_tool_specs(
    *,
    app_store: AppStore | None = None,
    runtime_store: RuntimeStore | None = None,
    recovery_store: RecoveryStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    observability_store=None,
    start_path: Path | None = None,
) -> list[tuple[McpToolDefinition, Any]]:
    """Build recovery MCP tool specs."""
    def _recovery_status_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if recovery_store is None:
            return {"status": None}
        return {
            "status": recovery_status(
                recovery_store,
                workspace_id=arguments.get("workspace_id") or context.workspace_id,
                session_id=arguments.get("session_id"),
            )
        }

    def _recovery_restart_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if recovery_store is None or runtime_store is None:
            return {"executed": False}
        intent, restarted = execute_session_restart(
            recovery_store,
            runtime_store=runtime_store,
            session_id=str(arguments["session_id"]),
            reason=str(arguments.get("reason") or "operator restart"),
            observability_store=observability_store,
        )
        return {"executed": True, "intent_id": intent.intent_id, "action": intent.action, "runtime_status": restarted.status}

    def _recovery_failed_start_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if recovery_store is None:
            return {"planned": False}
        failure, intent = record_failed_start(
            recovery_store,
            category=str(arguments["category"]),
            detail=str(arguments["detail"]),
            workspace_id=arguments.get("workspace_id") or context.workspace_id,
            session_id=arguments.get("session_id"),
            observability_store=observability_store,
        )
        return {"planned": True, "failure_id": failure.failure_id, "intent_id": intent.intent_id, "action": intent.action}

    def _recovery_health_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if recovery_store is None:
            return {"health": None}
        target_kind = str(arguments["target_kind"])
        if target_kind == "runtime":
            if runtime_store is None:
                return {"health": None}
            session = runtime_store.get_session(str(arguments["session_id"]))
            result = record_runtime_health(recovery_store, session=session, observability_store=observability_store)
        elif target_kind == "provider":
            if provider_registry is None:
                return {"health": None}
            result = record_provider_health(
                recovery_store,
                provider_registry=provider_registry,
                provider_id=str(arguments["provider_id"]),
                workspace_id=arguments.get("workspace_id") or context.workspace_id,
                observability_store=observability_store,
            )
        else:
            if app_store is None:
                return {"health": None}
            result = record_app_health(
                recovery_store,
                app_store=app_store,
                workspace_id=str(arguments.get("workspace_id") or context.workspace_id),
                app_id=str(arguments["app_id"]),
                start_path=start_path,
                observability_store=observability_store,
            )
        return {"health": {"target_kind": result.target_kind, "target_id": result.target_id, "status": result.status, "detail": result.detail}}

    tool_specs = [
        ("core.recovery.status", "Inspect recovery status for one workspace or runtime session.", _recovery_status_handler),
        ("core.recovery.restart", "Execute one runtime restart recovery action when allowed.", _recovery_restart_handler),
        ("core.recovery.failed_start", "Record one failed-start diagnosis and plan recovery.", _recovery_failed_start_handler),
        ("core.recovery.health", "Run one recovery health probe on demand.", _recovery_health_handler),
    ]
    return [
        (
            core_mcp_tool(
                tool_name=tool_name,
                description=description,
                owner_id="recovery",
                invocation_policy=OPERATOR_ONLY,
            ),
            handler,
        )
        for tool_name, description, handler in tool_specs
    ]
