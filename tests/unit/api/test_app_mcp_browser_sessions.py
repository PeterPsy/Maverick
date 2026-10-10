"""Platform browser cookies are delivered only through trusted MCP context."""

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.apps.contracts import parse_app_contract_file
from core.mcp.app_tools import _workspace_app_tool_definitions
from core.mcp.models import McpInvocationContext


class AppMcpBrowserSessionTests(unittest.TestCase):
    def test_delegation_uses_runtime_identity_and_revokes_failed_invocations(self):
        root = Path(__file__).resolve().parents[3]
        app = root / "apps/browser"
        parsed = parse_app_contract_file(app)
        binding = SimpleNamespace(app_id="browser", public_app_id="browser", data_root="/tmp/browser-fixture")
        actor = McpInvocationContext(caller_kind="sandbox_agent", workspace_id="default", agent_id="custom-agent",
                                     effective_mode="sandbox", user_id="user:owner", runtime_session_id="runtime:owner")
        grant = {"origin": "http://maverick.localhost:8014", "cookie_value": "private-cookie"}
        with (patch("core.mcp.app_tools.resolve_workspace_app_surface", return_value=(app, parsed)),
              patch("core.mcp.app_tools.resolve_app_secret_payload_requests", return_value=SimpleNamespace(secrets={}, errors=[])),
              patch("core.mcp.app_tools._app_dependencies_payload", return_value={}),
              patch("core.mcp.app_tools.issue_platform_browser_session", return_value=grant) as issue,
              patch("core.mcp.app_tools.revoke_platform_browser_session") as revoke,
              patch("core.mcp.app_tools.publish_declared_app_events"),
              patch("core.mcp.app_tools.run_json_entrypoint_with_sidecars", return_value={"session_id": "lab:test", "status_code": 200}) as invoke):
            definitions = _workspace_app_tool_definitions(object(), workspace_id="default", bindings=[binding],
                only_tool_name="app.browser.browser_session_create", identity_store="identity", runtime_store="runtime", start_path=root)
            definition, handler = definitions[0]
            self.assertTrue(definition.invocation_policy.sandbox_agent_allowed)
            self.assertEqual(handler({"mode": "maverick_dev_inspector"}, actor), {"session_id": "lab:test", "status_code": 200})
            issue.assert_called_once_with("identity", None, "runtime", user_id="user:owner", workspace_id="default", runtime_session_id="runtime:owner")
            self.assertEqual(invoke.call_args.kwargs["payload"]["platform_browser_session"], grant)
            self.assertNotIn("private-cookie", str(invoke.return_value))
            revoke.assert_not_called()
            invoke.return_value = {"status_code": 503, "error": "broker_unavailable"}
            handler({}, actor)
            revoke.assert_called_once_with("identity", "private-cookie")
            revoke.reset_mock()
            invoke.side_effect = TimeoutError("entrypoint timed out")
            with self.assertRaises(TimeoutError):
                handler({}, actor)
            revoke.assert_called_once_with("identity", "private-cookie")


if __name__ == "__main__":
    unittest.main()
