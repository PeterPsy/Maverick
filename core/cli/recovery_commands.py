"""Recovery-oriented core CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.apps.store import AppStore
from core.authorization.errors import AuthorizationError
from core.authorization.service import require_backend_restart_context, require_session_restart_context
from core.cli.core_command_helpers import FULL_ACCESS_WORKSPACE, WORKSPACE_SAFE, core_cli_command
from core.cli.errors import CliInvocationNotAllowedError
from core.cli.models import CliCommandDefinition, CliInvocationContext
from core.providers.provider_registry import ProviderRegistry
from core.recovery.backend_service import restart_backend_service
from core.recovery.service import execute_session_restart, record_app_health, record_failed_start, record_provider_health, record_runtime_health, recovery_status
from core.recovery.store import RecoveryStore
from core.runtime.store import RuntimeStore
from core.workspaces.store import WorkspaceStore


def recovery_command_specs(
    *,
    app_store: AppStore | None = None,
    runtime_store: RuntimeStore | None = None,
    recovery_store: RecoveryStore | None = None,
    workspace_store: WorkspaceStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    observability_store=None,
    start_path: Path | None = None,
) -> list[tuple[CliCommandDefinition, Any]]:
    """Build recovery command specs."""
    def _recovery_status_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if recovery_store is None:
            return {"status": None}
        return {
            "command_id": "core.recovery.status",
            "status": recovery_status(
                recovery_store,
                workspace_id=arguments.get("workspace_id") or context.workspace_id,
                session_id=arguments.get("session_id"),
            ),
        }

    def _recovery_restart_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if recovery_store is None or runtime_store is None:
            return {"planned": False}
        try:
            require_session_restart_context(
                runtime_store=runtime_store,
                workspace_store=workspace_store,
                session_id=str(arguments["session_id"]),
                workspace_id=context.workspace_id,
                user_id=context.user_id,
                caller_runtime_session_id=context.agent_id,
                platform_role=context.platform_role,
            )
        except AuthorizationError as error:
            raise CliInvocationNotAllowedError(error.reason) from error
        intent, restarted = execute_session_restart(
            recovery_store,
            runtime_store=runtime_store,
            session_id=str(arguments["session_id"]),
            reason=str(arguments.get("reason") or "operator restart"),
            observability_store=observability_store,
        )
        return {
            "command_id": "core.recovery.restart",
            "executed": True,
            "intent_id": intent.intent_id,
            "action": intent.action,
            "session_id": intent.session_id,
            "runtime_status": restarted.status,
        }

    def _recovery_backend_restart_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        try:
            require_backend_restart_context(
                workspace_id=context.workspace_id,
                effective_mode=context.effective_mode,
                platform_role=context.platform_role,
                workspace_role=context.workspace_role,
            )
        except AuthorizationError as error:
            raise CliInvocationNotAllowedError(error.reason) from error
        result = restart_backend_service(
            service_name=str(arguments.get("service_name") or "maverick-core.service"),
            health_url=str(arguments.get("health_url") or "http://127.0.0.1:8014/health"),
        )
        return {"command_id": "core.recovery.restart_backend", **result.to_payload()}

    def _recovery_failed_start_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
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
        return {
            "command_id": "core.recovery.failed_start",
            "planned": True,
            "failure_id": failure.failure_id,
            "intent_id": intent.intent_id,
            "action": intent.action,
        }

    def _recovery_health_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
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
        return {
            "command_id": "core.recovery.health",
            "health": {"target_kind": result.target_kind, "target_id": result.target_id, "status": result.status, "detail": result.detail},
        }

    command_specs = [
        ("core.recovery.status", ["core", "recovery", "status"], "Inspect recovery status for one workspace or runtime session.", WORKSPACE_SAFE, _recovery_status_handler),
        ("core.recovery.restart", ["core", "recovery", "restart"], "Execute one runtime-session restart recovery action when allowed.", WORKSPACE_SAFE, _recovery_restart_handler),
        ("core.recovery.restart_backend", ["core", "recovery", "backend-restart"], "Restart the Maverick backend host service and verify its health.", FULL_ACCESS_WORKSPACE, _recovery_backend_restart_handler),
        ("core.recovery.failed_start", ["core", "recovery", "failed-start"], "Record one failed-start diagnosis and plan recovery.", WORKSPACE_SAFE, _recovery_failed_start_handler),
        ("core.recovery.health", ["core", "recovery", "health"], "Run one recovery health probe on demand.", WORKSPACE_SAFE, _recovery_health_handler),
    ]
    return [
        (
            core_cli_command(
                command_id=command_id,
                path_segments=path_segments,
                description=description,
                owner_id="recovery",
                invocation_policy=invocation_policy,
            ),
            handler,
        )
        for command_id, path_segments, description, invocation_policy, handler in command_specs
    ]
