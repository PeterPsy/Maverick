from __future__ import annotations

import unittest

from core.cli.models import CliInvocationContext
from core.cli.registry_builder import list_core_cli_commands, run_core_cli_command
from core.jobs.errors import JobAuthorizationError, JobValidationError
from core.jobs.serialization import job_spec_to_payload
from core.mcp.models import McpInvocationContext
from core.mcp.registry_builder import call_mcp_tool, list_mcp_tools
from tests.unit.jobs.support import make_executor, make_service, make_spec


class JobSurfaceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.service, _clock = make_service()
        self.cli_context = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="workspace-a",
            agent_id="agent-one",
            effective_mode="sandbox",
        )
        self.mcp_context = McpInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="workspace-a",
            agent_id="agent-one",
            effective_mode="sandbox",
        )

    def test_cli_and_mcp_discover_generic_job_surfaces(self) -> None:
        command_ids = {item.command_id for item in list_core_cli_commands(job_service=self.service)}
        tool_names = {item.tool_name for item in list_mcp_tools(job_service=self.service)}
        expected = {"core.jobs.submit", "core.jobs.list", "core.jobs.get", "core.jobs.cancel"}
        self.assertTrue(expected.issubset(command_ids))
        self.assertTrue(expected.issubset(tool_names))

    def test_submit_cli_and_read_mcp_are_workspace_scoped(self) -> None:
        submitted = run_core_cli_command(
            command_id="core.jobs.submit",
            context=self.cli_context,
            arguments={"job_id": "job-one", "spec": job_spec_to_payload(make_spec())},
            job_service=self.service,
        )
        listed = call_mcp_tool(
            tool_name="core.jobs.list",
            context=self.mcp_context,
            arguments={},
            job_service=self.service,
        )
        detail = call_mcp_tool(
            tool_name="core.jobs.get",
            context=self.mcp_context,
            arguments={"job_id": "job-one", "include_history": True},
            job_service=self.service,
        )

        self.assertEqual(submitted["job"]["job_id"], "job-one")
        self.assertEqual(listed["jobs"][0]["job_id"], "job-one")
        self.assertEqual(detail["events"][0]["state"], "queued")

        with self.assertRaises(JobValidationError):
            run_core_cli_command(
                command_id="core.jobs.submit",
                context=self.cli_context,
                arguments={
                    "spec": job_spec_to_payload(
                        make_spec(workspace_id="workspace-b", idempotency_key="workspace-b")
                    )
                },
                job_service=self.service,
            )

    def test_forced_cancel_is_operator_only(self) -> None:
        self.service.submit(make_spec(), job_id="job-one")
        with self.assertRaisesRegex(JobAuthorizationError, "operator-only"):
            call_mcp_tool(
                tool_name="core.jobs.cancel",
                context=self.mcp_context,
                arguments={"job_id": "job-one", "reason": "force", "force": True},
                job_service=self.service,
            )

    def test_workspace_surfaces_never_expose_lease_authority(self) -> None:
        self.service.advertise_executor(make_executor())
        submitted = self.service.submit(make_spec(), job_id="job-one")
        leased = self.service.lease(
            submitted.job_id,
            workspace_id="workspace-a",
            executor_id="executor-a",
            lease_seconds=30,
        )
        assert leased.lease is not None

        detail = call_mcp_tool(
            tool_name="core.jobs.get",
            context=self.mcp_context,
            arguments={"job_id": "job-one"},
            job_service=self.service,
        )

        self.assertNotIn("lease_token", detail["job"]["lease"])
        self.assertNotIn(leased.lease.lease_token, str(detail))


if __name__ == "__main__":
    unittest.main()
