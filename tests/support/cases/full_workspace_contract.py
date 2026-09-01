from __future__ import annotations

from pathlib import Path
import time

from core.runtime.hosted_tool_process_registry import HostedToolProcessRegistry
from core.runtime.tool_catalog import RuntimeToolActorContext
from core.runtime.tool_core_capabilities import build_core_runtime_tool_capabilities
from core.runtime.tool_discovery_capabilities import build_discovery_first_capabilities
from tests.support.hosted_agentic_harness import HostedAgenticHarness


class FullWorkspaceContractFixture:
    def setUp(self) -> None:
        self.harness = HostedAgenticHarness(self)
        self.workspace = self.harness.root / "workspaces" / "default"
        self.context = RuntimeToolActorContext(
            workspace_id="default",
            actor_id="user-1",
            agent_id="agent-1",
            platform_role="admin",
            workspace_role="admin",
            session_id="session-hosted",
            execution_mode="full-access",
        )

    def _capabilities(self, *, processes: bool = False, race_hook=None):
        surfaces = build_core_runtime_tool_capabilities(
            workspace_id="default",
            workspace_root=self.workspace,
            runtime_root=Path(self.harness.session.runtime_root),
            process_registry=(
                HostedToolProcessRegistry(store=self.harness.store)
                if processes
                else None
            ),
            filesystem_race_hook=race_hook,
        )
        return {surface.definition.handle: surface for surface in surfaces}

    def _wait_for_process(self, capabilities, process_id: str):
        status = None
        for _ in range(150):
            status = capabilities["core-capability:process.status"].handler(
                {"process_id": process_id},
                self.context,
                None,
            )
            if status.payload["status"] != "running":
                return status
            time.sleep(0.02)
        self.fail(f"process {process_id} did not reach a terminal status")

    def _scope_digest(
        self,
        capabilities,
        path: str,
        *,
        target_is_directory: bool = False,
    ) -> str:
        result = capabilities[
            "core-capability:workspace.instructions"
        ].handler(
            {
                "path": path,
                "target_is_directory": target_is_directory,
            },
            self.context,
            None,
        )
        return str(result.payload["scope_digest"])

    @staticmethod
    def _discovery(cli, mcp):
        return {
            surface.definition.handle: surface
            for surface in build_discovery_first_capabilities(
                cli_registry=cli,
                mcp_registry=mcp,
            )
        }
