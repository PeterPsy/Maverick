from __future__ import annotations

from datetime import UTC, datetime
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.platform_state import bootstrap_platform_state
from core.runtime.execution import execute_runtime_turn
from core.runtime.hosted_agentic_factory import (
    _tool_orchestrator,
    classify_hosted_runtime_tool_result,
)
from core.runtime.hosted_tool_process_registry import HostedToolProcessRegistry
from core.runtime.tool_catalog import RuntimeToolActorContext
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient
from tests.support.hosted_agentic_harness import HostedAgenticHarness
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 8, 28, tzinfo=UTC)


class HostedAgenticFactoryToolsTest(unittest.TestCase):
    def test_production_composition_dispatches_and_continues_after_tool_result(self) -> None:
        harness = HostedAgenticHarness(self)
        with patch.dict(
            os.environ,
            {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"},
            clear=False,
        ):
            state = bootstrap_platform_state(
                start_path=harness.root,
                now=NOW,
                install_builtin_apps=False,
            )
        production_adapter = state.provider_registry.get_agentic_runtime_adapter(
            "maverick-tool-loop"
        )
        # Use the request builder selected by platform_state, not the harness
        # classifier called out by the P4 review.  The fixture catalog likewise
        # receives the exact production result-classification resolver.
        harness.request_builder = production_adapter.loop.request_builder
        harness.orchestrator.catalog_builder.result_classification_resolver = (
            classify_hosted_runtime_tool_result
        )
        client = DeterministicFakeAgenticClient(tool_name=harness.read_tool_name)

        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Use the public fixture tool and finish.",
            agentic_adapter=harness.adapter(client),
            provider_state=harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
        )

        self.assertEqual(result.exit_code, 0)
        self.assertGreaterEqual(len(client.requests), 2)
        invocation = harness.store.list_tool_invocations(
            session_id="session-hosted"
        )[0]
        self.assertEqual(invocation.state, "succeeded")
        self.assertEqual(invocation.result_data_class, "public")

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
            result_classification_resolver=classify_hosted_runtime_tool_result,
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
        self.assertEqual(cli_entry["result_data_class"], "public")
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
        self.assertEqual(cli_result.classification.data_class, "public")

        mcp_entry = self._discover(
            surfaces["core-capability:mcp.list"],
            actor,
            collection="tools",
            identity_field="tool_name",
            identity="developer-context.list",
        )
        self.assertEqual(mcp_entry["result_data_class"], "public")
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
        self.assertEqual(mcp_result.classification.data_class, "public")
        shell_classification = orchestrator.catalog_builder.result_classification_resolver(
            "core-capability:shell.run",
            {"argv": ["/bin/true"]},
            {"exit_code": 0, "output": ""},
            actor,
        )
        self.assertEqual(shell_classification.data_class, "public")

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
                    return {
                        **item,
                        "result_data_class": result.classification.data_class,
                    }
            next_cursor = result.payload["next_cursor"]
            if next_cursor is None:
                self.fail(f"{identity} was not exposed through {collection}")
            cursor = next_cursor


if __name__ == "__main__":
    unittest.main()
