"""Generic workspace app-interface resolution over official CLI/MCP surfaces."""

from __future__ import annotations

from pathlib import Path

from core.apps.dependencies import resolve_app_dependencies
from core.apps.store import AppStore
from core.cli.command_registry import CliCommandRegistry
from core.cli.models import CliInvocationContext
from core.cli.runner import CliRunner
from core.mcp.models import McpInvocationContext
from core.mcp.runner import McpRunner
from core.mcp.tool_registry import McpToolRegistry
from core.runtime.tool_catalog import (
    RuntimeAppInterfaceResolver,
    RuntimeExternalToolSurface,
    RuntimeToolActorContext,
)
from core.runtime.tool_errors import RuntimeToolError


class WorkspaceAppInterfaceResolver(RuntimeAppInterfaceResolver):
    """Map selected dependency providers to their already-mounted surfaces."""

    def __init__(
        self,
        *,
        app_store: AppStore,
        cli_registry: CliCommandRegistry,
        mcp_registry: McpToolRegistry,
        workspace_store=None,
        start_path: Path | None = None,
    ) -> None:
        self.app_store = app_store
        self.cli_registry = cli_registry
        self.mcp_registry = mcp_registry
        self.cli_runner = CliRunner(cli_registry)
        self.mcp_runner = McpRunner(mcp_registry)
        self.workspace_store = workspace_store
        self.start_path = start_path

    def list_tool_surfaces(
        self, *, context: RuntimeToolActorContext
    ) -> list[RuntimeExternalToolSurface]:
        return [item[0] for item in self._resolved_surfaces(context)]

    def invoke_tool_surface(
        self,
        *,
        handle: str,
        arguments: dict[str, object],
        context: RuntimeToolActorContext,
        idempotency_key: str | None,
    ) -> dict[str, object]:
        resolved = {surface.handle: target for surface, target in self._resolved_surfaces(context)}
        target = resolved.get(handle)
        if target is None:
            raise RuntimeToolError("tool_interface_unavailable")
        kind, source_id = target
        caller_kind = "sandbox_agent" if context.execution_mode == "sandbox" else "full_access_agent"
        if kind == "cli":
            return self.cli_runner.run_command(
                command_id=source_id,
                arguments=arguments,
                context=CliInvocationContext(
                    caller_kind=caller_kind,
                    workspace_id=context.workspace_id,
                    agent_id=context.agent_id,
                    effective_mode=context.execution_mode,
                    platform_role=context.platform_role,
                    user_id=context.actor_id,
                    workspace_role=context.workspace_role,
                    runtime_session_id=context.session_id,
                    idempotency_key=idempotency_key,
                ),
            )
        return self.mcp_runner.call_tool(
            tool_name=source_id,
            arguments=arguments,
            context=McpInvocationContext(
                caller_kind=caller_kind,
                workspace_id=context.workspace_id,
                agent_id=context.agent_id,
                effective_mode=context.execution_mode,
                platform_role=context.platform_role,
                user_id=context.actor_id,
                workspace_role=context.workspace_role,
                runtime_session_id=context.session_id,
                idempotency_key=idempotency_key,
            ),
        )

    def _resolved_surfaces(
        self, context: RuntimeToolActorContext
    ) -> list[tuple[RuntimeExternalToolSurface, tuple[str, str]]]:
        if not context.consumer_app_id:
            return []
        dependencies = resolve_app_dependencies(
            self.app_store,
            workspace_id=context.workspace_id,
            consumer_app_id=context.consumer_app_id,
            workspace_store=self.workspace_store,
            platform_role=context.platform_role,
            workspace_role=context.workspace_role,
            start_path=self.start_path,
        )
        resolved: list[tuple[RuntimeExternalToolSurface, tuple[str, str]]] = []
        for dependency in dependencies.get("dependencies", []):
            if not isinstance(dependency, dict) or dependency.get("status") != "resolved":
                continue
            interface_id = str(dependency.get("interface") or "").strip()
            selected = dependency.get("selected_provider_app_ids", [])
            candidates = dependency.get("candidates", [])
            if not interface_id or not isinstance(selected, list) or not isinstance(candidates, list):
                continue
            candidate_by_id = {
                str(item.get("app_id")): item for item in candidates if isinstance(item, dict)
            }
            for provider_id in sorted(str(item) for item in selected):
                candidate = candidate_by_id.get(provider_id, {})
                surface_kinds = set(candidate.get("surfaces", [])) if isinstance(candidate, dict) else set()
                if "cli" in surface_kinds:
                    resolved.extend(self._cli_surfaces(interface_id, provider_id, context.workspace_id))
                if "mcp" in surface_kinds:
                    resolved.extend(self._mcp_surfaces(interface_id, provider_id, context.workspace_id))
        resolved.sort(key=lambda item: item[0].handle)
        handles = [item[0].handle for item in resolved]
        if len(handles) != len(set(handles)):
            raise RuntimeToolError("tool_interface_mapping_collision")
        return resolved

    def _cli_surfaces(
        self, interface_id: str, provider_id: str, workspace_id: str
    ) -> list[tuple[RuntimeExternalToolSurface, tuple[str, str]]]:
        result = []
        for item in self.cli_registry.list_commands():
            if item.owner_kind != "app" or item.owner_id != provider_id:
                continue
            if item.workspace_id not in {None, workspace_id} or item.effect_class == "unclassified":
                continue
            surface = RuntimeExternalToolSurface(
                handle=f"app-interface:{interface_id}:{provider_id}:cli.{item.command_id}",
                description=item.description,
                input_schema=item.argument_schema,
                output_schema=None,
                effect_class=item.effect_class,
                supports_idempotency=item.supports_idempotency,
                safe_to_retry=item.safe_to_retry,
            )
            result.append((surface, ("cli", item.command_id)))
        return result

    def _mcp_surfaces(
        self, interface_id: str, provider_id: str, workspace_id: str
    ) -> list[tuple[RuntimeExternalToolSurface, tuple[str, str]]]:
        result = []
        for item in self.mcp_registry.list_tools():
            if item.owner_kind != "app" or item.owner_id != provider_id:
                continue
            if item.workspace_id not in {None, workspace_id} or item.effect_class == "unclassified":
                continue
            surface = RuntimeExternalToolSurface(
                handle=f"app-interface:{interface_id}:{provider_id}:mcp.{item.tool_name}",
                description=item.description,
                input_schema=item.input_schema,
                output_schema=item.output_schema,
                effect_class=item.effect_class,
                supports_idempotency=item.supports_idempotency,
                safe_to_retry=item.safe_to_retry,
            )
            result.append((surface, ("mcp", item.tool_name)))
        return result
