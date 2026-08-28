from __future__ import annotations

from datetime import UTC, datetime
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.platform_state import bootstrap_platform_state
from core.runtime.hosted_agentic_factory import _tool_orchestrator
from core.runtime.hosted_tool_process_registry import HostedToolProcessRegistry
from core.runtime.tool_catalog import RuntimeToolActorContext
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 8, 28, tzinfo=UTC)


class HostedAgenticFactoryToolsTest(unittest.TestCase):
    def test_official_cli_and_mcp_registries_are_discovered_and_invoked(self) -> None:
        root = make_temp_repo_root(self)
        workspace_root = root / "workspaces" / "default"
        runtime_root = workspace_root / "runtime"
        runtime_root.mkdir(parents=True)
        with patch.dict(
            os.environ,
            {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"},
            clear=False,
        ):
            state = bootstrap_platform_state(
                start_path=root,
                now=NOW,
                install_builtin_apps=False,
            )
        actor = RuntimeToolActorContext(
            workspace_id="default",
            actor_id="admin",
            agent_id="chat",
            platform_role="admin",
            workspace_role="owner",
            session_id="hosted-session",
            execution_mode="full-access",
        )
        context = SimpleNamespace(
            session=SimpleNamespace(
                workspace_id="default",
                workspace_root=str(workspace_root),
                runtime_root=str(runtime_root),
            )
        )
        orchestrator = _tool_orchestrator(
            context,
            actor=actor,
            state=state,
            ledger=state.runtime_tool_ledger,
            workspace_store=state.workspace_store,
            process_registry=HostedToolProcessRegistry(store=state.runtime_store),
        )
        surfaces = {
            item.definition.handle: item
            for item in orchestrator.catalog_builder.core_capabilities
        }

        cli_entry = self._discover(
            surfaces["core-capability:cli.list"],
            actor,
            collection="commands",
            identity_field="command_id",
            identity="developer-context.list",
        )
        cli_result = surfaces["core-capability:cli.run"].handler(
            {
                "command_id": "developer-context.list",
                "invocation_token": cli_entry["invocation_token"],
                "arguments": {},
            },
            actor,
            None,
        )
        self.assertEqual(
            cli_result.payload["command_id"],
            "developer-context.list",
        )

        mcp_entry = self._discover(
            surfaces["core-capability:mcp.list"],
            actor,
            collection="tools",
            identity_field="tool_name",
            identity="developer-context.list",
        )
        mcp_result = surfaces["core-capability:mcp.call"].handler(
            {
                "tool_name": "developer-context.list",
                "invocation_token": mcp_entry["invocation_token"],
                "arguments": {},
            },
            actor,
            None,
        )
        self.assertIn("items", mcp_result.payload)

    def _discover(
        self,
        surface,
        actor,
        *,
        collection: str,
        identity_field: str,
        identity: str,
    ) -> dict[str, object]:
        cursor = 0
        while True:
            result = surface.handler(
                {"cursor": cursor, "max_results": 50},
                actor,
                None,
            )
            for item in result.payload[collection]:
                if item[identity_field] == identity:
                    return item
            next_cursor = result.payload["next_cursor"]
            if next_cursor is None:
                self.fail(f"{identity} was not exposed through {collection}")
            cursor = next_cursor


if __name__ == "__main__":
    unittest.main()
