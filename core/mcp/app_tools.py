"""App-contributed MCP tool mounting."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.apps.store import AppStore
from core.mcp.models import McpInvocationContext, McpInvocationPolicy, McpToolDefinition
from core.shared.entrypoints import run_json_entrypoint
from core.workspaces.paths import workspace_paths

def _workspace_app_tool_definitions(
    store: AppStore,
    *,
    workspace_id: str,
    app_event_bus=None,
    start_path: Path | None = None,
) -> list[tuple[McpToolDefinition, Any]]:
    definitions: list[tuple[McpToolDefinition, Any]] = []
    for binding in enabled_workspace_app_bindings(store, workspace_id=workspace_id):
        source_root, parsed = resolve_workspace_app_surface(store, binding=binding, start_path=start_path)
        if not parsed.contract.capabilities.mcp_tools:
            continue
        if parsed.contract.entrypoints.mcp is None:
            raise ValueError(
                f"App `{parsed.app_id}` declares MCP tools but no MCP entrypoint in its contract."
            )
        entrypoint_path = str((source_root / parsed.contract.entrypoints.mcp).resolve())
        paths = workspace_paths(workspace_id=workspace_id, start_path=start_path)
        for tool_name in parsed.contract.capabilities.mcp_tools:
            hosted_tool_name = f"app.{parsed.app_id}.{tool_name}"
            def _handler(
                arguments: dict[str, Any],
                context: McpInvocationContext,
                *,
                _entrypoint_path: str = entrypoint_path,
                _tool_name: str = tool_name,
                _workspace_id: str = workspace_id,
                _source_root: Path = source_root,
                _app_id: str = parsed.app_id,
                _data_root: str = binding.data_root,
                _workspace_root: str = str(paths.root),
                _uploaded_storage_root: str = str(paths.uploaded_storage),
                _generated_storage_root: str = str(paths.generated_storage),
                _app_event_bus=app_event_bus,
            ) -> dict[str, Any]:
                result = run_json_entrypoint(
                    _entrypoint_path,
                    payload={
                        "surface": "mcp",
                        "tool_name": _tool_name,
                        "workspace_id": _workspace_id,
                        "app_id": _app_id,
                        "workspace_root": _workspace_root,
                        "data_root": _data_root,
                        "uploaded_storage_root": _uploaded_storage_root,
                        "generated_storage_root": _generated_storage_root,
                        "arguments": arguments,
                    },
                    cwd=_source_root,
                )
                _publish_app_events(
                    _app_event_bus,
                    result,
                    workspace_id=_workspace_id,
                    app_id=_app_id,
                )
                return result

            definitions.append(
                (
                    McpToolDefinition(
                        tool_name=hosted_tool_name,
                        description=f"App MCP tool exposed by `{parsed.app_id}`.",
                        input_schema={"type": "object"},
                        output_schema={"type": "object"},
                        owner_kind="app",
                        owner_id=parsed.app_id,
                        workspace_id=workspace_id,
                        exposure_scope="workspace_enabled_app",
                        invocation_policy=McpInvocationPolicy(
                            operator_only=False,
                            sandbox_agent_allowed=True,
                            requires_workspace_context=True,
                            requires_full_access=False,
                        ),
                        entrypoint_path=entrypoint_path,
                    ),
                    lambda arguments, context, _handler=_handler: _handler(arguments, context),
                )
            )
    return definitions


def _publish_app_events(app_event_bus, result: dict[str, Any], *, workspace_id: str, app_id: str) -> None:
    if app_event_bus is None:
        return
    events = result.get("app_events", [])
    if not isinstance(events, list):
        return
    for event in events:
        if not isinstance(event, dict):
            continue
        app_event_bus.publish(
            {
                "type": str(event.get("type") or "maverick.app.data-changed"),
                "workspace_id": workspace_id,
                "owner_app_id": str(event.get("owner_app_id") or app_id),
                "resource": str(event.get("resource") or ""),
            }
        )
