"""Generated contract smoke test."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(APP_ROOT))

from core.apps.contracts import parse_app_contract_file

from backend.service import DEFAULT_ENDPOINT, InvocationContext, handle_action


class GeneratedAppContractTest(unittest.TestCase):
    def test_contract_parses(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)
        self.assertEqual(parsed.app_id, "fusion-connector")
        self.assertEqual(parsed.contract.presentation.frontend_role, "none")
        self.assertEqual(parsed.contract.compatibility.supported_workspace_modes, ["full-access"])

    def test_descriptors_cover_declared_surfaces(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)
        tools = json.loads((APP_ROOT / "mcp" / "tool_schemas.json").read_text(encoding="utf-8"))["tools"]
        commands = json.loads((APP_ROOT / "cli" / "command_schemas.json").read_text(encoding="utf-8"))["commands"]
        self.assertEqual(sorted(parsed.contract.capabilities.mcp_tools), sorted(tools))
        self.assertEqual(sorted(parsed.contract.capabilities.cli_commands), sorted(commands))
        self.assertFalse(parsed.contract.capabilities.views)


class FakeFusionMcpHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        length = int(self.headers.get("Content-Length", "0") or "0")
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        self.__class__.requests.append(payload)
        method = payload.get("method")
        if method == "notifications/initialized":
            self.send_response(202)
            self.end_headers()
            return
        if method == "initialize":
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "result": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "serverInfo": {"name": "fake-fusion", "version": "test"},
                    },
                }
            )
            return
        if method == "tools/list":
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "result": {
                        "tools": [
                            {
                                "name": "fusion_mcp_read",
                                "description": "Read Fusion documents, projects, and screenshots.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {"queryType": {"type": "string"}, "operation": {"type": "string"}},
                                },
                            },
                            {
                                "name": "get_document_info",
                                "description": "Return active document info.",
                                "inputSchema": {"type": "object", "properties": {}},
                            },
                            {
                                "name": "create_box",
                                "description": "Create a box.",
                                "inputSchema": {"type": "object", "properties": {"size": {"type": "number"}}},
                            },
                        ]
                    },
                }
            )
            return
        if method == "tools/call":
            params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            if arguments.get("queryType") == "document" and arguments.get("operation") == "open":
                self._send(
                    {
                        "jsonrpc": "2.0",
                        "id": payload.get("id"),
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(
                                        {
                                            "success": True,
                                            "message": "1 open document(s)",
                                            "results": [
                                                {
                                                    "name": "Bauliera v4",
                                                    "isActive": True,
                                                    "isModified": False,
                                                    "isReadOnly": False,
                                                    "isSaved": True,
                                                    "parentFolder": "Camperizzazione macchina",
                                                    "parentProject": "Camperizzazione macchina",
                                                    "id": "hidden-from-brief",
                                                }
                                            ],
                                        }
                                    ),
                                }
                            ]
                        },
                    }
                )
                return
            if arguments.get("queryType") == "screenshot":
                self._send(
                    {
                        "jsonrpc": "2.0",
                        "id": payload.get("id"),
                        "result": {
                            "content": [
                                {
                                    "type": "image",
                                    "mimeType": "image/png",
                                    "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=",
                                }
                            ]
                        },
                    }
                )
                return
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "result": {"content": [{"type": "text", "text": "{\"success\": true, \"message\": \"ok\"}"}]},
                }
            )
            return
        self._send({"jsonrpc": "2.0", "id": payload.get("id"), "error": {"code": -32601, "message": "missing"}})

    def _send(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Mcp-Session-Id", "fake-session")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FusionConnectorServiceTest(unittest.TestCase):
    def test_default_config_is_loopback(self) -> None:
        with TemporaryDirectory() as tmp:
            status, result = handle_action(Path(tmp), "config_get", {})
        self.assertEqual(status, 200)
        self.assertEqual(result["config"]["endpoint"], DEFAULT_ENDPOINT)

    def test_remote_endpoint_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            status, result = handle_action(
                Path(tmp),
                "config_set",
                {"confirm": True, "endpoint": "https://example.com/mcp"},
            )
        self.assertEqual(status, 400)
        self.assertIn("loopback", result["error"])

    def test_discovers_and_calls_fake_fusion_mcp(self) -> None:
        FakeFusionMcpHandler.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeFusionMcpHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        endpoint = f"http://127.0.0.1:{server.server_port}/mcp"
        try:
            with TemporaryDirectory() as tmp:
                data_root = Path(tmp)
                context = InvocationContext(surface="test", effective_mode="full-access")
                status, _result = handle_action(
                    data_root,
                    "config_set",
                    {"confirm": True, "endpoint": endpoint, "tool_denylist": []},
                    context=context,
                )
                self.assertEqual(status, 200)
                status, result = handle_action(data_root, "list_tools", {}, context=context)
                self.assertEqual(status, 200)
                self.assertEqual(
                    [tool["name"] for tool in result["tools"]],
                    ["fusion_mcp_read", "get_document_info", "create_box"],
                )

                status, result = handle_action(
                    data_root,
                    "call_tool",
                    {"fusion_tool_name": "get_document_info", "tool_arguments": {}},
                    context=context,
                )
                self.assertEqual(status, 200)
                self.assertEqual(result["fusion_result_summary"]["fusion_success"], True)
                self.assertEqual(result["fusion_result_summary"]["fusion_message"], "ok")

                status, result = handle_action(
                    data_root,
                    "call_tool",
                    {"fusion_tool_name": "create_box", "tool_arguments": {"size": 10}},
                    context=context,
                )
                self.assertEqual(status, 428)
                self.assertTrue(result["confirmation_required"])

                status, result = handle_action(
                    data_root,
                    "call_tool",
                    {"fusion_tool_name": "create_box", "tool_arguments": {"size": 10}, "confirm": True},
                    context=context,
                )
                self.assertEqual(status, 200)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

    def test_session_brief_combines_tools_and_open_document_context(self) -> None:
        FakeFusionMcpHandler.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeFusionMcpHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        endpoint = f"http://127.0.0.1:{server.server_port}/mcp"
        try:
            with TemporaryDirectory() as tmp:
                status, result = handle_action(
                    Path(tmp),
                    "session_brief",
                    {"endpoint": endpoint},
                    context=InvocationContext(surface="test", effective_mode="full-access"),
                )
                self.assertEqual(status, 200)
                self.assertTrue(result["connected"])
                self.assertEqual(result["tool_names"], ["fusion_mcp_read", "get_document_info", "create_box"])
                self.assertNotIn("input_schema", result["tools"][0])
                self.assertEqual(result["tools"][0]["input_properties"], ["operation", "queryType"])
                self.assertEqual(result["open_documents"]["count"], 1)
                self.assertEqual(result["open_documents"]["active_document"]["name"], "Bauliera v4")
                self.assertNotIn("id", result["open_documents"]["active_document"])
                methods = [request.get("method") for request in FakeFusionMcpHandler.requests]
                self.assertEqual(
                    methods,
                    ["initialize", "notifications/initialized", "tools/list", "tools/call"],
                )
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

    def test_capture_screenshot_saves_image_without_inline_base64(self) -> None:
        FakeFusionMcpHandler.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeFusionMcpHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        endpoint = f"http://127.0.0.1:{server.server_port}/mcp"
        try:
            with TemporaryDirectory() as tmp:
                data_root = Path(tmp)
                status, result = handle_action(
                    data_root,
                    "capture_screenshot",
                    {"endpoint": endpoint, "width": 320, "height": 240, "direction": "iso-top-right"},
                    context=InvocationContext(surface="test", effective_mode="full-access"),
                )
                self.assertEqual(status, 200)
                self.assertTrue(result["ok"])
                self.assertNotIn("result", result)
                screenshot = result["screenshot"]
                self.assertEqual(screenshot["mime_type"], "image/png")
                self.assertEqual(screenshot["width"], 320)
                self.assertEqual(screenshot["height"], 240)
                self.assertTrue(screenshot["workspace_relative_path"].startswith("data/fusion-connector/screenshots/"))

                image_path = data_root / screenshot["app_data_relative_path"]
                self.assertTrue(image_path.exists())
                self.assertEqual(image_path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(screenshot["bytes"], image_path.stat().st_size)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()


if __name__ == "__main__":
    unittest.main()
