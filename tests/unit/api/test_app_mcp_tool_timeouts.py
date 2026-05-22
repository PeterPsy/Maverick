from __future__ import annotations

import unittest

from core.mcp.app_tools import APP_MCP_ENTRYPOINT_TIMEOUT_SECONDS, app_mcp_entrypoint_timeout_seconds
from core.mcp.models import McpInvocationContext


class AppMcpToolTimeoutTestCase(unittest.TestCase):
    def test_direct_app_mcp_context_uses_default_entrypoint_timeout(self) -> None:
        context = McpInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id=None,
            effective_mode="sandbox",
        )

        self.assertIsNone(context.app_mcp_timeout_seconds)
        self.assertEqual(app_mcp_entrypoint_timeout_seconds(context), APP_MCP_ENTRYPOINT_TIMEOUT_SECONDS)

    def test_request_context_can_override_app_mcp_entrypoint_timeout(self) -> None:
        context = McpInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id=None,
            effective_mode="sandbox",
            app_mcp_timeout_seconds=2.0,
        )

        self.assertEqual(app_mcp_entrypoint_timeout_seconds(context), 2.0)


if __name__ == "__main__":
    unittest.main()
