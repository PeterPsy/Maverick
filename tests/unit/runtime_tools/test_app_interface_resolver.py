from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.cli.command_registry import CliCommandRegistry
from core.cli.models import CliCommandDefinition, CliInvocationPolicy
from core.mcp.models import McpInvocationPolicy, McpToolDefinition
from core.mcp.tool_registry import McpToolRegistry
from core.runtime.tool_app_interfaces import WorkspaceAppInterfaceResolver
from core.runtime.tool_catalog import RuntimeToolActorContext


SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
    "additionalProperties": False,
}


class WorkspaceAppInterfaceResolverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cli = CliCommandRegistry()
        self.mcp = McpToolRegistry()
        self.seen_idempotency_key = None
        self.cli.register_command(
            CliCommandDefinition(
                command_id="app.docs.lookup",
                path_segments=["app", "docs", "lookup"],
                description="Look up a document.",
                argument_schema=SCHEMA,
                owner_kind="app",
                owner_id="docs",
                workspace_id="default",
                exposure_scope="workspace_enabled_app",
                invocation_policy=CliInvocationPolicy(False, None, True, True, False),
                entrypoint_path="cli.py",
                effect_class="read",
                safe_to_retry=True,
            ),
            self._lookup,
        )
        self.mcp.register_tool(
            McpToolDefinition(
                tool_name="app.docs.update",
                description="Update a document.",
                input_schema=SCHEMA,
                output_schema={"type": "object"},
                owner_kind="app",
                owner_id="docs",
                workspace_id="default",
                exposure_scope="workspace_enabled_app",
                invocation_policy=McpInvocationPolicy(False, True, True, False),
                entrypoint_path="mcp.py",
                effect_class="mutating",
                supports_idempotency=True,
            ),
            lambda arguments, _context: {"query": arguments["query"]},
        )
        self.resolver = WorkspaceAppInterfaceResolver(
            app_store=SimpleNamespace(),  # type: ignore[arg-type]
            cli_registry=self.cli,
            mcp_registry=self.mcp,
        )
        self.context = RuntimeToolActorContext(
            workspace_id="default",
            actor_id="user-1",
            agent_id="chat",
            platform_role=None,
            workspace_role="member",
            session_id="session-interface",
            execution_mode="sandbox",
            consumer_app_id="chat",
        )

    def _lookup(self, arguments, context):
        self.seen_idempotency_key = context.idempotency_key
        return {"query": arguments["query"]}

    @patch("core.runtime.tool_app_interfaces.resolve_app_dependencies")
    def test_selected_provider_maps_to_and_invokes_official_surfaces(self, resolve) -> None:
        resolve.return_value = {
            "dependencies": [
                {
                    "status": "resolved",
                    "interface": "documents.v1",
                    "selected_provider_app_ids": ["docs"],
                    "candidates": [{"app_id": "docs", "surfaces": ["cli", "mcp"]}],
                }
            ]
        }

        surfaces = self.resolver.list_tool_surfaces(context=self.context)

        self.assertEqual(
            [item.handle for item in surfaces],
            [
                "app-interface:documents.v1:docs:cli.app.docs.lookup",
                "app-interface:documents.v1:docs:mcp.app.docs.update",
            ],
        )
        self.assertEqual([item.effect_class for item in surfaces], ["read", "mutating"])
        result = self.resolver.invoke_tool_surface(
            handle=surfaces[0].handle,
            arguments={"query": "roadmap"},
            context=self.context,
            idempotency_key="idempotency-1",
        )
        self.assertEqual(result, {"query": "roadmap"})
        self.assertEqual(self.seen_idempotency_key, "idempotency-1")

    def test_runtime_without_consumer_app_has_no_implicit_provider(self) -> None:
        context = replace(self.context, consumer_app_id=None)
        self.assertEqual(self.resolver.list_tool_surfaces(context=context), [])


if __name__ == "__main__":
    unittest.main()
