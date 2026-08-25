from __future__ import annotations

import unittest

from core.cli.models import CliInvocationContext
from core.cli.recovery_commands import recovery_command_specs
from core.cli.runner import _enforce_invocation_policy
from core.cli.runtime_provider_commands import runtime_provider_command_specs
from core.cli.errors import CliInvocationNotAllowedError
from core.mcp.errors import McpInvocationNotAllowedError
from core.mcp.models import McpInvocationContext
from core.mcp.recovery_tools import recovery_tool_specs
from core.mcp.runner import enforce_mcp_invocation_policy
from core.mcp.runtime_provider_tools import runtime_provider_tool_specs
from core.recovery.health_request import (
    RECOVERY_HEALTH_INPUT_SCHEMA,
    RecoveryHealthArgumentError,
    parse_recovery_health_target,
)


class RecoveryDiagnosticSurfaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cli_context = CliInvocationContext(
            caller_kind="operator",
            workspace_id="default",
            agent_id=None,
            effective_mode="full-access",
        )
        self.mcp_context = McpInvocationContext(
            caller_kind="operator",
            workspace_id="default",
            agent_id=None,
            effective_mode="full-access",
        )

    def test_health_target_validation_returns_stable_argument_errors(self) -> None:
        invalid_requests = (
            ({}, "target_kind_required"),
            ({"target_kind": "other"}, "target_kind_invalid"),
            ({"target_kind": "runtime"}, "session_id_required"),
            ({"target_kind": "provider"}, "provider_id_required"),
            ({"target_kind": "app"}, "app_id_required"),
        )
        for arguments, expected_code in invalid_requests:
            with self.subTest(arguments=arguments):
                with self.assertRaises(RecoveryHealthArgumentError) as caught:
                    parse_recovery_health_target(arguments)
                self.assertEqual(caught.exception.code, expected_code)

        self.assertEqual(
            parse_recovery_health_target(
                {"target_kind": "runtime", "session_id": "session-1"}
            ),
            ("runtime", "session-1"),
        )

    def test_health_surfaces_publish_schema_and_never_leak_key_error(self) -> None:
        cli_definition, cli_handler = next(
            item
            for item in recovery_command_specs()
            if item[0].command_id == "core.recovery.health"
        )
        mcp_definition, mcp_handler = next(
            item
            for item in recovery_tool_specs()
            if item[0].tool_name == "core.recovery.health"
        )

        self.assertEqual(cli_definition.argument_schema, RECOVERY_HEALTH_INPUT_SCHEMA)
        self.assertEqual(mcp_definition.input_schema, RECOVERY_HEALTH_INPUT_SCHEMA)
        self.assertEqual(cli_handler({}, self.cli_context)["error"], "target_kind_required")
        self.assertEqual(mcp_handler({}, self.mcp_context)["error"], "target_kind_required")

    def test_runtime_status_and_health_diagnostics_are_operator_only(self) -> None:
        cli_definitions = {
            definition.command_id: definition
            for definition, _handler in (
                *runtime_provider_command_specs(),
                *recovery_command_specs(),
            )
        }
        mcp_definitions = {
            definition.tool_name: definition
            for definition, _handler in (
                *runtime_provider_tool_specs(),
                *recovery_tool_specs(),
            )
        }
        for surface_id in ("core.runtime.status", "core.recovery.health"):
            with self.subTest(surface_id=surface_id):
                cli_policy = cli_definitions[surface_id].invocation_policy
                mcp_policy = mcp_definitions[surface_id].invocation_policy
                self.assertTrue(cli_policy.operator_only)
                self.assertTrue(mcp_policy.operator_only)
                with self.assertRaises(CliInvocationNotAllowedError):
                    _enforce_invocation_policy(
                        cli_policy,
                        CliInvocationContext(
                            caller_kind="sandbox_agent",
                            workspace_id="default",
                            agent_id="agent-1",
                            effective_mode="sandbox",
                        ),
                    )
                with self.assertRaises(McpInvocationNotAllowedError):
                    enforce_mcp_invocation_policy(
                        mcp_policy,
                        McpInvocationContext(
                            caller_kind="sandbox_agent",
                            workspace_id="default",
                            agent_id="agent-1",
                            effective_mode="sandbox",
                        ),
                    )


if __name__ == "__main__":
    unittest.main()
