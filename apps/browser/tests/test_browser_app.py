from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import select
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from core.apps.contracts import parse_app_contract_file


APP_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = APP_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from service import acceptance_smoke_payload, handle_action, mcp_result_for_tool
from store import load_state


class BrowserAppTests(unittest.TestCase):
    def test_contract_declares_sealed_p0_browser_surfaces(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)

        self.assertEqual(parsed.app_id, "browser")
        self.assertEqual(parsed.contract.distribution.mode, "sealed")
        self.assertEqual(parsed.contract.distribution.source_access, "none")
        self.assertEqual(parsed.contract.presentation.frontend_role, "workspace")
        self.assertEqual(parsed.contract.compatibility.supported_workspace_modes, ["full-access"])
        self.assertEqual(parsed.contract.storage.primary_paths, ["data/browser/state.json"])
        self.assertIn("browser_navigate", parsed.contract.capabilities.mcp_tools)
        self.assertIn("browser_click", parsed.contract.capabilities.mcp_tools)
        self.assertNotIn("browser_evaluate", parsed.contract.capabilities.mcp_tools)
        self.assertNotIn("browser_run_code", parsed.contract.capabilities.mcp_tools)

    def test_frontend_declares_p0_browser_lab_panes_without_external_iframes(self) -> None:
        html = (APP_ROOT / "frontend" / "src" / "index.html").read_text(encoding="utf-8")
        javascript = (APP_ROOT / "frontend" / "src" / "assets" / "main.js").read_text(encoding="utf-8")

        self.assertIn('id="url-input"', html)
        self.assertIn('id="session-picker"', html)
        self.assertIn('id="tab-list"', html)
        self.assertIn('id="snapshot-output"', html)
        self.assertIn('id="refs-list"', html)
        self.assertIn('id="screenshot-frame"', html)
        self.assertIn('id="console-list"', html)
        self.assertIn('id="network-list"', html)
        self.assertIn('id="policy-status"', html)
        self.assertNotIn("<iframe", html.lower())
        self.assertIn('"session.create"', javascript)
        self.assertIn('"navigate"', javascript)
        self.assertIn('"snapshot"', javascript)
        self.assertIn('"screenshot"', javascript)
        self.assertIn('"console.messages"', javascript)
        self.assertIn('"network.requests"', javascript)
        self.assertIn("refreshInspectionPanes", javascript)
        self.assertIn("markRefreshFailure", javascript)
        self.assertIn("maverick.app.ready", javascript)
        self.assertNotIn("Promise.allSettled", javascript)

    def test_mcp_descriptor_matches_p0_tool_scope(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)
        descriptor = json.loads((APP_ROOT / "mcp" / "tool_schemas.json").read_text(encoding="utf-8"))
        cli_descriptor = json.loads((APP_ROOT / "cli" / "command_schemas.json").read_text(encoding="utf-8"))

        expected_tools = {
            "browser_session_create",
            "browser_session_close",
            "browser_navigate",
            "browser_snapshot",
            "browser_take_screenshot",
            "browser_console_messages",
            "browser_network_requests",
            "browser_tabs",
            "browser_wait_for",
            "browser_click",
            "browser_type",
            "browser_press_key",
        }

        self.assertEqual(set(parsed.contract.capabilities.mcp_tools), expected_tools)
        self.assertEqual(set(descriptor["tools"]), expected_tools)
        self.assertNotIn("browser_evaluate", descriptor["tools"])
        self.assertNotIn("browser_run_code", descriptor["tools"])
        for tool in descriptor["tools"].values():
            self.assertIs(tool["input_schema"].get("additionalProperties"), False)
        self.assertIn("acceptance.smoke", cli_descriptor["commands"]["browser"]["argument_schema"]["properties"]["action"]["enum"])

    def test_mcp_rejects_prohibited_or_unknown_tool_names(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            evaluate_status, evaluate_result = mcp_result_for_tool(
                data_root,
                "browser_evaluate",
                {"session_id": "session-1", "script": "document.cookie"},
            )
            run_code_status, run_code_result = mcp_result_for_tool(
                data_root,
                "browser_run_code",
                {"session_id": "session-1", "code": "return 1"},
            )

        self.assertEqual(evaluate_status, 400)
        self.assertEqual(evaluate_result["error"], "unsupported_tool")
        self.assertEqual(run_code_status, 400)
        self.assertEqual(run_code_result["error"], "unsupported_tool")

    def test_mcp_rejects_arguments_outside_p0_contract(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            status_code, result = mcp_result_for_tool(
                data_root,
                "browser_snapshot",
                {"session_id": "session-1", "script": "document.body.innerText"},
            )

        self.assertEqual(status_code, 400)
        self.assertEqual(result["error"], "validation_error")
        self.assertEqual(result["field"], "script")

    def test_mcp_rejects_caller_supplied_action_override(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            status_code, result = mcp_result_for_tool(
                data_root,
                "browser_snapshot",
                {"action": "status"},
            )

        self.assertEqual(status_code, 400)
        self.assertEqual(result["error"], "validation_error")
        self.assertEqual(result["field"], "action")
        self.assertNotIn("p0_scope", result)

    def test_mcp_rejects_invalid_p0_argument_values_before_broker_handoff(self) -> None:
        cases = [
            (
                "browser_console_messages",
                {"session_id": "session-1", "limit": 1000000000},
                "limit",
            ),
            (
                "browser_network_requests",
                {"session_id": "session-1", "limit": 0},
                "limit",
            ),
            (
                "browser_navigate",
                {"session_id": "session-1", "url": "https://93.184.216.34/", "mode": 123},
                "mode",
            ),
            (
                "browser_console_messages",
                {"session_id": "session-1", "limit": True},
                "limit",
            ),
            (
                "browser_take_screenshot",
                {"session_id": "session-1", "full_page": "yes"},
                "full_page",
            ),
            (
                "browser_wait_for",
                {"session_id": "session-1", "state": "selector:#secret", "timeout_ms": 1},
                "state",
            ),
            (
                "browser_wait_for",
                {"session_id": "session-1", "timeout_ms": True},
                "timeout_ms",
            ),
            (
                "browser_click",
                {
                    "session_id": "session-1",
                    "ref": " ",
                    "target_url": "http://hostmachine:8000/apps/base-shell/",
                    "mode": "maverick_dev_inspector",
                },
                "ref",
            ),
        ]
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            for tool_name, arguments, field in cases:
                with self.subTest(tool_name=tool_name):
                    status_code, result = mcp_result_for_tool(data_root, tool_name, arguments, workspace_role="admin")
                    self.assertEqual(status_code, 400)
                    self.assertEqual(result["error"], "validation_error")
                    self.assertEqual(result["field"], field)

    def test_mcp_interactive_tools_require_dev_inspector_mode_argument(self) -> None:
        with broker_stub({"session_id": "session-1"}) as broker:
            with TemporaryDirectory() as temp_dir:
                data_root = Path(temp_dir)
                with patch.dict(
                    "os.environ",
                    {"MAVERICK_BROWSER_BROKER_URL": broker.url, "MAVERICK_BROWSER_BROKER_TOKEN": "test-token"},
                ):
                    handle_action(
                        data_root,
                        {"action": "session.create", "mode": "maverick_dev_inspector"},
                        workspace_role="admin",
                    )
                    status_code, result = mcp_result_for_tool(
                        data_root,
                        "browser_click",
                        {
                            "session_id": "session-1",
                            "ref": "button-1",
                            "target_url": "http://hostmachine:8000/app/chat",
                        },
                        workspace_role="admin",
                    )

        self.assertEqual(status_code, 403)
        self.assertEqual(result["error"], "policy_denied")
        self.assertEqual(result["policy"]["reason"], "blocked_interactive_action_mode_required")
        self.assertEqual([item["action"] for item in broker.actions], ["session.create"])

    def test_policy_preflight_uses_core_browser_egress_policy(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            denied_status, denied = handle_action(data_root, {"action": "policy.preflight", "url": "file:///etc/passwd"})
            denied_dev_status, denied_dev = handle_action(
                data_root,
                {
                    "action": "policy.preflight",
                    "url": "http://hostmachine:8000/apps/base-shell/",
                    "mode": "maverick_dev_inspector",
                },
            )
            dev_status, dev = handle_action(
                data_root,
                {
                    "action": "policy.preflight",
                    "url": "http://hostmachine:8000/apps/base-shell/",
                    "mode": "maverick_dev_inspector",
                },
                workspace_role="admin",
            )

        self.assertEqual(denied_status, 200)
        self.assertFalse(denied["policy"]["allowed"])
        self.assertEqual(denied["policy"]["reason"], "blocked_disallowed_scheme")
        self.assertEqual(denied_dev_status, 200)
        self.assertFalse(denied_dev["policy"]["allowed"])
        self.assertEqual(denied_dev["policy"]["reason"], "blocked_admin_dev_target_not_enabled")
        self.assertEqual(dev_status, 200)
        self.assertTrue(dev["policy"]["allowed"])
        self.assertEqual(dev["policy"]["reason"], "allowed_admin_dev_target")

    def test_policy_preflight_rejects_caller_supplied_dns_results(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            status_code, result = handle_action(
                data_root,
                {
                    "action": "policy.preflight",
                    "url": "https://example.com/",
                    "resolved_addresses": ["93.184.216.34"],
                },
            )

        self.assertEqual(status_code, 400)
        self.assertEqual(result["error"], "validation_error")
        self.assertEqual(result["field"], "resolved_addresses")

    def test_policy_preflight_redacts_url_secrets_in_response(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            status_code, result = handle_action(
                data_root,
                {
                    "action": "policy.preflight",
                    "url": "http://user:pass@93.184.216.34/private?token=secret#fragment",
                },
            )

        policy = result["policy"]
        self.assertEqual(status_code, 200)
        self.assertTrue(policy["allowed"])
        self.assertEqual(policy["url"], "http://93.184.216.34/private?redacted")
        self.assertEqual(policy["redacted_url"], "http://93.184.216.34/private?redacted")
        self.assertNotIn("user:pass", json.dumps(policy))
        self.assertNotIn("token=secret", json.dumps(policy))

    def test_status_reports_unreachable_broker_without_failing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            with patch.dict("os.environ", {"MAVERICK_BROWSER_BROKER_URL": "http://127.0.0.1:1"}):
                status_code, result = handle_action(data_root, {"action": "status"})

        self.assertEqual(status_code, 200)
        self.assertEqual(result["broker"]["provider"], "playwright_lab")
        self.assertEqual(result["broker"]["status"], "unreachable")

    def test_acceptance_smoke_runs_p0_broker_sequence_without_persisting_artifacts(self) -> None:
        action_responses = {
            "session.create": {"session_id": "stub-session", "isolated": True, "persistent_profile": False},
            "navigate": {"session_id": "stub-session", "url": "https://93.184.216.34/", "title": "Example"},
            "snapshot": {"session_id": "stub-session", "snapshot": "body text"},
            "screenshot": {
                "session_id": "stub-session",
                "mime_type": "image/png",
                "encoding": "base64",
                "data": "aW1hZ2U=",
                "persisted": False,
            },
            "console.messages": {"session_id": "stub-session", "messages": []},
            "network.requests": {"session_id": "stub-session", "requests": [{"event": "request", "url": "https://93.184.216.34/"}]},
            "tabs": {"sessions": [{"session_id": "stub-session", "tabs": [{"url": "https://93.184.216.34/", "active": True}]}]},
            "session.close": {"session_id": "stub-session", "closed": True},
        }
        with broker_stub(action_responses) as broker:
            with TemporaryDirectory() as temp_dir:
                data_root = Path(temp_dir)
                with patch.dict(
                    "os.environ",
                    {"MAVERICK_BROWSER_BROKER_URL": broker.url, "MAVERICK_BROWSER_BROKER_TOKEN": "test-token"},
                ):
                    status_code, result = acceptance_smoke_payload(
                        data_root,
                        {"action": "acceptance.smoke", "url": "https://93.184.216.34/"},
                    )

        self.assertEqual(status_code, 200)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["checks"]["session_create"])
        self.assertTrue(result["checks"]["navigate"])
        self.assertTrue(result["checks"]["snapshot"])
        self.assertTrue(result["checks"]["screenshot"])
        self.assertTrue(result["checks"]["console_messages"])
        self.assertTrue(result["checks"]["network_requests"])
        self.assertTrue(result["checks"]["session_close"])
        self.assertEqual(
            [item["action"] for item in broker.actions],
            [
                "session.create",
                "navigate",
                "snapshot",
                "screenshot",
                "console.messages",
                "network.requests",
                "tabs",
                "session.close",
            ],
        )
        screenshot_step = next(step for step in result["steps"] if step["action"] == "screenshot")
        self.assertEqual(screenshot_step["screenshot_bytes"], len("aW1hZ2U="))
        self.assertNotIn("data", screenshot_step)

    def test_session_create_rejects_persistent_profile_options(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            status_code, result = handle_action(
                data_root,
                {
                    "action": "session.create",
                    "mode": "read_only",
                    "storage_state": {"cookies": []},
                },
            )
            state = load_state(str(data_root))

        self.assertEqual(status_code, 400)
        self.assertEqual(result["error"], "validation_error")
        self.assertEqual(result["field"], "storage_state")
        self.assertEqual(state["audit"][-1]["action"], "session.create")
        self.assertEqual(state["audit"][-1]["status"], "invalid")
        self.assertEqual(state["audit"][-1]["reason"], "validation_error")

    def test_session_create_delegates_to_configured_broker_and_audits_success(self) -> None:
        with broker_stub({"session_id": "stub-session", "isolated": True, "persistent_profile": False}) as broker:
            with TemporaryDirectory() as temp_dir:
                data_root = Path(temp_dir)
                with patch.dict(
                    "os.environ",
                    {"MAVERICK_BROWSER_BROKER_URL": broker.url, "MAVERICK_BROWSER_BROKER_TOKEN": "test-token"},
                ):
                    status_code, result = handle_action(data_root, {"action": "session.create", "mode": "read_only"})
                    status_payload_code, status_payload = handle_action(data_root, {"action": "status"})
                state = load_state(str(data_root))

        self.assertEqual(status_code, 201)
        self.assertEqual(result["session_id"], "stub-session")
        self.assertEqual(broker.actions[-1]["action"], "session.create")
        self.assertEqual(broker.actions[-1]["payload"]["mode"], "read_only")
        self.assertEqual(broker.actions[-1]["payload"]["policy_context"], {"allow_admin_dev_targets": False})
        self.assertEqual(broker.actions[-1]["payload"]["caller_context"], {"admin_dev_targets_enabled": False})
        self.assertEqual(broker.authorizations[-1], "Bearer test-token")
        self.assertIn("stub-session", state["sessions"])
        self.assertEqual(state["sessions"]["stub-session"]["mode"], "read_only")
        self.assertEqual(state["sessions"]["stub-session"]["tabs"], [{"url": "about:blank", "active": True}])
        self.assertEqual(status_payload_code, 200)
        self.assertEqual(status_payload["sessions"][0]["session_id"], "stub-session")
        self.assertEqual(state["audit"][-1]["action"], "session.create")
        self.assertEqual(state["audit"][-1]["status"], "ok")

    def test_session_create_reads_runtime_token_file_when_env_token_is_not_available(self) -> None:
        with broker_stub({"session_id": "stub-session", "isolated": True, "persistent_profile": False}) as broker:
            with TemporaryDirectory() as temp_dir:
                data_root = Path(temp_dir) / "data"
                token_file = Path(temp_dir) / "browser-token"
                token_file.write_text("file-token\n", encoding="utf-8")
                token_file.chmod(0o600)
                env = {
                    "MAVERICK_BROWSER_BROKER_URL": broker.url,
                    "MAVERICK_BROWSER_BROKER_TOKEN": "",
                    "MAVERICK_BROWSER_BROKER_TOKEN_FILE": str(token_file),
                }
                with patch.dict("os.environ", env, clear=False):
                    status_code, result = handle_action(data_root, {"action": "session.create", "mode": "read_only"})

        self.assertEqual(status_code, 201)
        self.assertEqual(result["session_id"], "stub-session")
        self.assertEqual(broker.authorizations[-1], "Bearer file-token")

    def test_session_close_removes_local_session_record(self) -> None:
        action_responses = {
            "session.create": {"session_id": "stub-session"},
            "session.close": {"session_id": "stub-session", "closed": True},
        }
        with broker_stub(action_responses) as broker:
            with TemporaryDirectory() as temp_dir:
                data_root = Path(temp_dir)
                with patch.dict(
                    "os.environ",
                    {"MAVERICK_BROWSER_BROKER_URL": broker.url, "MAVERICK_BROWSER_BROKER_TOKEN": "test-token"},
                ):
                    handle_action(data_root, {"action": "session.create", "mode": "read_only"})
                    close_status, close_result = handle_action(
                        data_root,
                        {"action": "session.close", "session_id": "stub-session"},
                    )
                state = load_state(str(data_root))

        self.assertEqual(close_status, 200)
        self.assertTrue(close_result["closed"])
        self.assertEqual(state["sessions"], {})
        self.assertEqual([item["action"] for item in broker.actions], ["session.create", "session.close"])

    def test_trusted_policy_context_cannot_be_supplied_by_caller(self) -> None:
        with broker_stub({"session_id": "stub-session"}) as broker:
            with TemporaryDirectory() as temp_dir:
                data_root = Path(temp_dir)
                with patch.dict(
                    "os.environ",
                    {"MAVERICK_BROWSER_BROKER_URL": broker.url, "MAVERICK_BROWSER_BROKER_TOKEN": "test-token"},
                ):
                    create_status, create_result = handle_action(
                        data_root,
                        {"action": "session.create", "mode": "maverick_dev_inspector"},
                        workspace_role="admin",
                    )
                    status_code, result = handle_action(
                        data_root,
                        {
                            "action": "navigate",
                            "session_id": create_result["session_id"],
                            "url": "http://hostmachine:8000/apps/base-shell/",
                            "mode": "maverick_dev_inspector",
                            "policy_context": {"allow_admin_dev_targets": False},
                        },
                        workspace_role="admin",
                    )

        self.assertEqual(create_status, 201)
        self.assertEqual(status_code, 400)
        self.assertEqual(result["error"], "validation_error")
        self.assertEqual(result["field"], "policy_context")
        self.assertEqual([item["action"] for item in broker.actions], ["session.create"])

    def test_admin_context_is_forwarded_for_dev_session_reads(self) -> None:
        with broker_stub({"session_id": "stub-session", "snapshot": "ok"}) as broker:
            with TemporaryDirectory() as temp_dir:
                data_root = Path(temp_dir)
                with patch.dict(
                    "os.environ",
                    {"MAVERICK_BROWSER_BROKER_URL": broker.url, "MAVERICK_BROWSER_BROKER_TOKEN": "test-token"},
                ):
                    handle_action(
                        data_root,
                        {"action": "session.create", "mode": "maverick_dev_inspector"},
                        workspace_role="admin",
                    )
                    status_code, result = handle_action(
                        data_root,
                        {"action": "snapshot", "session_id": "stub-session"},
                        workspace_role="admin",
                    )

        self.assertEqual(status_code, 200)
        self.assertEqual(result["session_id"], "stub-session")
        self.assertEqual(broker.actions[-1]["action"], "snapshot")
        self.assertEqual(broker.actions[-1]["payload"]["caller_context"], {"admin_dev_targets_enabled": True})

    def test_backend_tracks_navigation_tabs_console_and_network_metadata(self) -> None:
        action_responses = {
            "session.create": {"session_id": "stub-session", "isolated": True, "persistent_profile": False},
            "navigate": {"session_id": "stub-session", "url": "https://93.184.216.34/page?redacted", "title": "Example"},
            "tabs": {
                "sessions": [
                    {
                        "session_id": "stub-session",
                        "tabs": [{"url": "https://93.184.216.34/page?redacted", "active": True}],
                    }
                ]
            },
            "console.messages": {"session_id": "stub-session", "messages": [{"type": "log", "text": "ready"}]},
            "network.requests": {"session_id": "stub-session", "requests": [{"event": "request", "url": "https://93.184.216.34/"}]},
        }
        with broker_stub(action_responses) as broker:
            with TemporaryDirectory() as temp_dir:
                data_root = Path(temp_dir)
                with patch.dict(
                    "os.environ",
                    {"MAVERICK_BROWSER_BROKER_URL": broker.url, "MAVERICK_BROWSER_BROKER_TOKEN": "test-token"},
                ):
                    handle_action(data_root, {"action": "session.create", "mode": "read_only"})
                    navigate_status, navigate_result = handle_action(
                        data_root,
                        {"action": "navigate", "session_id": "stub-session", "url": "https://93.184.216.34/page?token=secret"},
                    )
                    tabs_status, _tabs_result = handle_action(data_root, {"action": "tabs", "session_id": "stub-session"})
                    console_status, _console_result = handle_action(
                        data_root,
                        {"action": "console.messages", "session_id": "stub-session"},
                    )
                    network_status, _network_result = handle_action(
                        data_root,
                        {"action": "network.requests", "session_id": "stub-session"},
                    )
                state = load_state(str(data_root))

        session = state["sessions"]["stub-session"]
        self.assertEqual(navigate_status, 200)
        self.assertEqual(navigate_result["url"], "https://93.184.216.34/page?redacted")
        self.assertEqual(tabs_status, 200)
        self.assertEqual(console_status, 200)
        self.assertEqual(network_status, 200)
        self.assertEqual(session["url"], "https://93.184.216.34/page?redacted")
        self.assertEqual(session["title"], "Example")
        self.assertEqual(session["tabs"], [{"active": True, "url": "https://93.184.216.34/page?redacted"}])
        self.assertEqual(session["console"], [{"type": "log", "text": "ready"}])
        self.assertEqual(session["network"], [{"event": "request", "url": "https://93.184.216.34/"}])
        self.assertEqual(
            [item["action"] for item in broker.actions],
            ["session.create", "navigate", "tabs", "console.messages", "network.requests"],
        )

    def test_non_admin_cannot_read_dev_inspector_session(self) -> None:
        with broker_stub({"session_id": "stub-session"}) as broker:
            with TemporaryDirectory() as temp_dir:
                data_root = Path(temp_dir)
                with patch.dict(
                    "os.environ",
                    {"MAVERICK_BROWSER_BROKER_URL": broker.url, "MAVERICK_BROWSER_BROKER_TOKEN": "test-token"},
                ):
                    handle_action(
                        data_root,
                        {"action": "session.create", "mode": "maverick_dev_inspector"},
                        workspace_role="admin",
                    )
                    status_code, result = handle_action(data_root, {"action": "snapshot", "session_id": "stub-session"})
                state = load_state(str(data_root))

        self.assertEqual(status_code, 403)
        self.assertEqual(result["error"], "policy_denied")
        self.assertEqual(result["policy"]["reason"], "blocked_admin_dev_session_not_authorized")
        self.assertEqual([item["action"] for item in broker.actions], ["session.create"])
        self.assertEqual(state["audit"][-1]["action"], "snapshot")
        self.assertEqual(state["audit"][-1]["status"], "denied")

    def test_non_admin_status_and_audit_hide_dev_inspector_session(self) -> None:
        with broker_stub({"session_id": "stub-session"}) as broker:
            with TemporaryDirectory() as temp_dir:
                data_root = Path(temp_dir)
                with patch.dict(
                    "os.environ",
                    {"MAVERICK_BROWSER_BROKER_URL": broker.url, "MAVERICK_BROWSER_BROKER_TOKEN": "test-token"},
                ):
                    handle_action(
                        data_root,
                        {"action": "session.create", "mode": "maverick_dev_inspector"},
                        workspace_role="admin",
                    )
                    member_status_code, member_status = handle_action(data_root, {"action": "status"})
                    member_audit_code, member_audit = handle_action(data_root, {"action": "audit.list"})
                    admin_status_code, admin_status = handle_action(
                        data_root,
                        {"action": "status"},
                        workspace_role="admin",
                    )
                    admin_audit_code, admin_audit = handle_action(
                        data_root,
                        {"action": "audit.list"},
                        workspace_role="admin",
                    )

        self.assertEqual(member_status_code, 200)
        self.assertEqual(member_status["session_count"], 0)
        self.assertEqual(member_status["sessions"], [])
        self.assertEqual(member_status["audit_count"], 0)
        self.assertEqual(member_audit_code, 200)
        self.assertEqual(member_audit["audit"], [])
        self.assertEqual(admin_status_code, 200)
        self.assertEqual(admin_status["session_count"], 1)
        self.assertEqual(admin_status["sessions"][0]["session_id"], "stub-session")
        self.assertEqual(admin_audit_code, 200)
        self.assertEqual(admin_audit["audit"][-1]["action"], "session.create")
        self.assertEqual(admin_audit["audit"][-1]["mode"], "maverick_dev_inspector")

    def test_non_admin_audit_hides_closed_dev_inspector_session_records(self) -> None:
        action_responses = {
            "session.create": {"session_id": "stub-session"},
            "snapshot": {"session_id": "stub-session", "snapshot": "ok"},
            "session.close": {"session_id": "stub-session", "closed": True},
        }
        with broker_stub(action_responses) as broker:
            with TemporaryDirectory() as temp_dir:
                data_root = Path(temp_dir)
                with patch.dict(
                    "os.environ",
                    {"MAVERICK_BROWSER_BROKER_URL": broker.url, "MAVERICK_BROWSER_BROKER_TOKEN": "test-token"},
                ):
                    handle_action(
                        data_root,
                        {"action": "session.create", "mode": "maverick_dev_inspector"},
                        workspace_role="admin",
                    )
                    handle_action(
                        data_root,
                        {"action": "snapshot", "session_id": "stub-session"},
                        workspace_role="admin",
                    )
                    handle_action(
                        data_root,
                        {"action": "session.close", "session_id": "stub-session"},
                        workspace_role="admin",
                    )
                    member_audit_code, member_audit = handle_action(data_root, {"action": "audit.list"})
                    admin_audit_code, admin_audit = handle_action(
                        data_root,
                        {"action": "audit.list"},
                        workspace_role="admin",
                    )

        self.assertEqual(member_audit_code, 200)
        self.assertEqual(member_audit["audit"], [])
        self.assertEqual(admin_audit_code, 200)
        self.assertEqual([item["action"] for item in admin_audit["audit"]], ["session.create", "snapshot", "session.close"])
        self.assertEqual({item["mode"] for item in admin_audit["audit"]}, {"maverick_dev_inspector"})

    def test_broker_token_is_required_before_handoff(self) -> None:
        with broker_stub({"session_id": "stub-session"}) as broker:
            with TemporaryDirectory() as temp_dir:
                data_root = Path(temp_dir)
                with patch.dict(
                    "os.environ",
                    {
                        "MAVERICK_BROWSER_BROKER_URL": broker.url,
                        "MAVERICK_BROWSER_BROKER_TOKEN": "",
                        "MAVERICK_BROWSER_BROKER_TOKEN_FILE": str(Path(temp_dir) / "missing-token"),
                    },
                    clear=False,
                ):
                    status_code, result = handle_action(data_root, {"action": "session.create", "mode": "read_only"})

        self.assertEqual(status_code, 503)
        self.assertEqual(result["error"], "broker_unavailable")
        self.assertEqual(broker.actions, [])

    def test_navigation_denial_is_audited_before_broker_handoff(self) -> None:
        with broker_stub({"session_id": "stub-session"}) as broker:
            with TemporaryDirectory() as temp_dir:
                data_root = Path(temp_dir)
                with patch.dict(
                    "os.environ",
                    {"MAVERICK_BROWSER_BROKER_URL": broker.url, "MAVERICK_BROWSER_BROKER_TOKEN": "test-token"},
                ):
                    handle_action(data_root, {"action": "session.create", "mode": "read_only"})
                    status_code, result = handle_action(
                        data_root,
                        {
                            "action": "navigate",
                            "session_id": "stub-session",
                            "url": "http://169.254.169.254/latest/meta-data/",
                        },
                    )
                state = load_state(str(data_root))

        self.assertEqual(status_code, 403)
        self.assertEqual(result["error"], "policy_denied")
        self.assertEqual([item["action"] for item in broker.actions], ["session.create"])
        self.assertEqual(state["audit"][-1]["action"], "navigate")
        self.assertEqual(state["audit"][-1]["status"], "denied")

    def test_dev_inspector_click_is_policy_checked_then_blocks_on_missing_broker(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            with broker_stub({"session_id": "session-1"}) as broker:
                with patch.dict(
                    "os.environ",
                    {"MAVERICK_BROWSER_BROKER_URL": broker.url, "MAVERICK_BROWSER_BROKER_TOKEN": "test-token"},
                ):
                    handle_action(
                        data_root,
                        {"action": "session.create", "mode": "maverick_dev_inspector"},
                        workspace_role="admin",
                    )
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_BROWSER_BROKER_URL": "http://127.0.0.1:1",
                    "MAVERICK_BROWSER_BROKER_TOKEN": "",
                    "MAVERICK_BROWSER_BROKER_TOKEN_FILE": str(Path(temp_dir) / "missing-token"),
                },
                clear=False,
            ):
                status_code, result = mcp_result_for_tool(
                    data_root,
                    "browser_click",
                    {
                        "session_id": "session-1",
                        "ref": "button-1",
                        "target_url": "http://hostmachine:8000/app/chat",
                        "mode": "maverick_dev_inspector",
                    },
                    workspace_role="admin",
                )
            state = load_state(str(data_root))

        self.assertEqual(status_code, 503)
        self.assertEqual(result["error"], "broker_unavailable")
        self.assertEqual(state["audit"][-1]["action"], "click")
        self.assertEqual(state["audit"][-1]["status"], "blocked")

    def test_install_hook_creates_state_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            completed = subprocess.run(
                [sys.executable, str(APP_ROOT / "hooks" / "install.py")],
                input=json.dumps({"data_root": str(data_root)}),
                text=True,
                capture_output=True,
                check=True,
                cwd=str(APP_ROOT),
            )
            output = json.loads(completed.stdout)

            self.assertEqual(output["status"], "ok")
            self.assertTrue((data_root / "state.json").is_file())

    def test_health_hook_fails_when_active_broker_is_unavailable(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            env = dict(os.environ)
            env.pop("MAVERICK_BROWSER_BROKER_TOKEN", None)
            env["MAVERICK_BROWSER_BROKER_URL"] = "http://127.0.0.1:1"
            completed = subprocess.run(
                [sys.executable, str(APP_ROOT / "hooks" / "health_check.py")],
                input=json.dumps({"data_root": str(data_root)}),
                text=True,
                capture_output=True,
                check=False,
                cwd=str(APP_ROOT),
                env=env,
            )
            output = json.loads(completed.stdout)

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(output["status"], "degraded")
        self.assertEqual(output["broker"]["status"], "unreachable")

    def test_health_hook_fails_when_broker_token_is_rejected(self) -> None:
        with broker_stub({"session_id": "stub-session"}) as broker:
            with TemporaryDirectory() as temp_dir:
                data_root = Path(temp_dir)
                env = dict(os.environ)
                env["MAVERICK_BROWSER_BROKER_URL"] = broker.url
                env["MAVERICK_BROWSER_BROKER_TOKEN"] = "wrong-token"
                completed = subprocess.run(
                    [sys.executable, str(APP_ROOT / "hooks" / "health_check.py")],
                    input=json.dumps({"data_root": str(data_root)}),
                    text=True,
                    capture_output=True,
                    check=False,
                    cwd=str(APP_ROOT),
                    env=env,
                )
                output = json.loads(completed.stdout)

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(output["status"], "degraded")
        self.assertEqual(output["broker"]["http_status"], 401)
        self.assertEqual(output["broker"]["error"], "unauthorized")
        self.assertEqual(broker.health_authorizations[-1], "Bearer wrong-token")

    def test_health_hook_fails_when_playwright_connect_check_is_degraded(self) -> None:
        with broker_stub({"session_id": "stub-session"}, active_connected=False) as broker:
            with TemporaryDirectory() as temp_dir:
                data_root = Path(temp_dir)
                env = dict(os.environ)
                env["MAVERICK_BROWSER_BROKER_URL"] = broker.url
                env["MAVERICK_BROWSER_BROKER_TOKEN"] = "test-token"
                completed = subprocess.run(
                    [sys.executable, str(APP_ROOT / "hooks" / "health_check.py")],
                    input=json.dumps({"data_root": str(data_root)}),
                    text=True,
                    capture_output=True,
                    check=False,
                    cwd=str(APP_ROOT),
                    env=env,
                )
                output = json.loads(completed.stdout)

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(output["status"], "degraded")
        self.assertEqual(output["broker"]["status"], "degraded")
        self.assertEqual(output["broker"]["http_status"], 503)
        self.assertFalse(output["broker"]["connected"])

    def test_health_hook_passes_only_after_active_broker_connect_check(self) -> None:
        with broker_stub({"session_id": "stub-session"}) as broker:
            with TemporaryDirectory() as temp_dir:
                data_root = Path(temp_dir)
                env = dict(os.environ)
                env["MAVERICK_BROWSER_BROKER_URL"] = broker.url
                env["MAVERICK_BROWSER_BROKER_TOKEN"] = "test-token"
                completed = subprocess.run(
                    [sys.executable, str(APP_ROOT / "hooks" / "health_check.py")],
                    input=json.dumps({"data_root": str(data_root)}),
                    text=True,
                    capture_output=True,
                    check=True,
                    cwd=str(APP_ROOT),
                    env=env,
                )
                output = json.loads(completed.stdout)

        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["broker"]["status"], "ready")
        self.assertTrue(output["broker"]["connected"])
        self.assertEqual(broker.health_authorizations[-1], "Bearer test-token")

    def test_docker_helper_uses_pinned_playwright_run_server(self) -> None:
        completed = subprocess.run(
            ["node", str(APP_ROOT / "broker" / "playwright-server-docker.mjs"), "--print"],
            text=True,
            capture_output=True,
            check=True,
            cwd=str(APP_ROOT),
        )

        command = completed.stdout.strip()
        self.assertIn("mcr.microsoft.com/playwright:v1.60.0-noble", command)
        self.assertIn("playwright@1.60.0 run-server", command)
        self.assertIn("--add-host hostmachine:host-gateway", command)
        self.assertIn("--user pwuser", command)

    def test_broker_generates_local_token_file_when_env_token_is_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "broker-token"
            env = dict(os.environ)
            env.pop("MAVERICK_BROWSER_BROKER_TOKEN", None)
            env["MAVERICK_BROWSER_BROKER_TOKEN_FILE"] = str(token_file)
            env["MAVERICK_BROWSER_BROKER_PORT"] = "0"
            env["MAVERICK_BROWSER_PROXY_PORT"] = "0"
            process = subprocess.Popen(
                ["node", str(APP_ROOT / "broker" / "playwright-broker.mjs")],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(APP_ROOT),
                env=env,
            )
            try:
                line = read_process_line(process)
                output = json.loads(line)
                token = token_file.read_text(encoding="utf-8").strip()
                token_mode = stat.S_IMODE(token_file.stat().st_mode)
            finally:
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=5)

        self.assertEqual(output["status"], "listening")
        self.assertEqual(output["token_source"], "file")
        self.assertRegex(token, r"^[0-9a-f]{64}$")
        self.assertEqual(token_mode, 0o600)
        self.assertNotIn(token, line)

    def test_broker_policy_self_test_blocks_restricted_targets(self) -> None:
        completed = subprocess.run(
            ["node", str(APP_ROOT / "broker" / "playwright-broker.mjs"), "--self-test-policy"],
            text=True,
            capture_output=True,
            check=True,
            cwd=str(APP_ROOT),
        )

        output = json.loads(completed.stdout)
        self.assertEqual(output["status"], "ok")


class BrokerStub:
    def __init__(
        self,
        server: HTTPServer,
        thread: threading.Thread,
        actions: list[dict],
        authorizations: list[str],
        health_authorizations: list[str],
        url: str,
    ) -> None:
        self.server = server
        self.thread = thread
        self.actions = actions
        self.authorizations = authorizations
        self.health_authorizations = health_authorizations
        self.url = url

    def __enter__(self) -> "BrokerStub":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


def broker_stub(
    action_response: dict,
    *,
    expected_token: str = "test-token",
    active_connected: bool = True,
) -> BrokerStub:
    actions: list[dict] = []
    authorizations: list[str] = []
    health_authorizations: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if not self.path.startswith("/health"):
                self.send_response(404)
                self.end_headers()
                return
            authorization = self.headers.get("Authorization", "")
            health_authorizations.append(authorization)
            if authorization != f"Bearer {expected_token}":
                self._send_json(
                    {"error": "unauthorized", "detail": "Browser broker token is missing or invalid."},
                    status=401,
                )
                return
            connect_check = "check=connect" in self.path
            if connect_check and not active_connected:
                self._send_json(
                    {
                        "status": "degraded",
                        "provider": "playwright_lab",
                        "connected": False,
                        "error": "playwright_server_unavailable",
                        "detail": "Cannot connect to Playwright run-server.",
                        "session_count": 0,
                    },
                    status=503,
                )
                return
            self._send_json(
                {
                    "status": "ready",
                    "provider": "playwright_lab",
                    "connected": connect_check,
                    "session_count": 0,
                }
            )

        def do_POST(self) -> None:
            if self.path != "/actions":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            authorizations.append(self.headers.get("Authorization", ""))
            actions.append(body)
            action = body.get("action")
            if isinstance(action, str) and action in action_response and isinstance(action_response[action], dict):
                payload = action_response[action]
            else:
                payload = action_response
            status = 201 if action == "session.create" else 200
            self._send_json(payload, status=status)

        def log_message(self, format: str, *args) -> None:
            return

        def _send_json(self, payload: dict, *, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return BrokerStub(server, thread, actions, authorizations, health_authorizations, f"http://{host}:{port}")


def read_process_line(process: subprocess.Popen[str], *, timeout_seconds: float = 5.0) -> str:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.stdout is not None and select.select([process.stdout], [], [], 0.1)[0]:
            line = process.stdout.readline()
            if line:
                return line
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise AssertionError(f"Browser broker exited before writing readiness JSON: {stderr}")
    raise AssertionError("Timed out waiting for Browser broker readiness JSON.")


if __name__ == "__main__":
    unittest.main()
