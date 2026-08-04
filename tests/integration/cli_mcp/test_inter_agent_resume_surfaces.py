"""Hosted scheduler handoff coverage for inter-agent operator surfaces."""

from __future__ import annotations

from dataclasses import replace

from core.cli.models import CliInvocationContext
from core.cli.service import run_core_cli_command
from core.inter_agent.errors import InterAgentOperationError
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from core.mcp.models import McpInvocationContext
from core.mcp.service import call_mcp_tool
from tests.support.surfaces import SurfaceTestBase
from tests.unit.inter_agent.test_dynamic_orchestration_service import orchestrated_spec


class InterAgentResumeSurfaceTest(SurfaceTestBase):
    def test_cli_and_mcp_orchestrated_resume_use_hosted_handoff(self) -> None:
        repo_root = self.make_repo_root()
        runtime_store = self.make_runtime_store()
        inter_agent_store = build_inter_agent_document_store(start_path=repo_root)
        service = InterAgentService(inter_agent_store)
        cli_run = service.create_run(replace(orchestrated_spec(), idempotency_key="cli-resume"))
        mcp_run = service.create_run(replace(orchestrated_spec(), idempotency_key="mcp-resume"))
        inter_agent_store.save_run(replace(cli_run, status="paused"))
        inter_agent_store.save_run(replace(mcp_run, status="paused"))
        cli_context = CliInvocationContext(
            caller_kind="operator",
            workspace_id="default",
            agent_id=None,
            effective_mode="full-access",
            user_id="operator",
        )
        mcp_context = McpInvocationContext(
            caller_kind="operator",
            workspace_id="default",
            agent_id=None,
            effective_mode="full-access",
            user_id="operator",
        )
        handoffs: list[tuple[str, str]] = []

        def hosted_handoff(_state, run_service, *, workspace_id, run_id, reason):
            handoffs.append((run_id, reason))
            return run_service.resume_run(
                workspace_id=workspace_id,
                run_id=run_id,
                reason=reason,
            )

        cli_result = run_core_cli_command(
            command_id="inter-agent.runs.resume",
            context=cli_context,
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            workspace_id="default",
            start_path=repo_root,
            orchestration_resume=hosted_handoff,
            arguments={"run_id": cli_run.run_id, "reason": "cli_resume"},
        )
        mcp_result = call_mcp_tool(
            tool_name="inter_agent_resume",
            context=mcp_context,
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            workspace_id="default",
            start_path=repo_root,
            orchestration_resume=hosted_handoff,
            arguments={"run_id": mcp_run.run_id, "reason": "mcp_resume"},
        )

        self.assertEqual(cli_result["run"]["status"], "running")
        self.assertEqual(mcp_result["run"]["status"], "running")
        self.assertEqual(handoffs, [(cli_run.run_id, "cli_resume"), (mcp_run.run_id, "mcp_resume")])

        blocked_run = service.create_run(replace(orchestrated_spec(), idempotency_key="blocked-resume"))
        inter_agent_store.save_run(replace(blocked_run, status="paused"))
        with self.assertRaisesRegex(InterAgentOperationError, "hosted core"):
            run_core_cli_command(
                command_id="inter-agent.runs.resume",
                context=cli_context,
                runtime_store=runtime_store,
                inter_agent_store=inter_agent_store,
                workspace_id="default",
                start_path=repo_root,
                arguments={"run_id": blocked_run.run_id},
            )
        self.assertEqual(inter_agent_store.get_run(blocked_run.run_id, workspace_id="default").status, "paused")
