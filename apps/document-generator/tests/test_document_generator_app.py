"""Tests for the Document Generator app."""

from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.contracts import parse_app_contract_file
from core.cli.models import CliInvocationContext
from core.cli.service import list_core_cli_commands, run_core_cli_command
from core.mcp.models import McpInvocationContext
from core.mcp.service import call_mcp_tool, list_mcp_tools
from core.shared.entrypoints import run_json_entrypoint
from core.skills.service import list_available_workspace_skills
from tests.support.markers import integration_test


REPO_ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = REPO_ROOT / "apps" / "document-generator"


class DocumentGeneratorAppTestCase(unittest.TestCase):
    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        source_apps_root = REPO_ROOT / "apps"
        for app_id in ("base-shell", "chat", "document-generator", "skills"):
            shutil.copytree(
                source_apps_root / app_id,
                repo_root / "apps" / app_id,
                ignore=shutil.ignore_patterns("node_modules", "__pycache__"),
            )
        return repo_root

    def invoke(self, app, *, path: str, method: str = "GET", body: dict | None = None, cookie: str | None = None) -> tuple[int, dict | bytes, dict[str, str]]:
        payload = b"" if body is None else json.dumps(body).encode("utf-8")
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(payload)),
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": "",
            "wsgi.input": BytesIO(payload),
        }
        if cookie is not None:
            environ["HTTP_COOKIE"] = cookie

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        raw = b"".join(app(environ, start_response))
        status = int(headers["__status__"].split()[0])
        if "application/json" in headers.get("Content-Type", ""):
            return status, json.loads(raw.decode("utf-8")), headers
        return status, raw, headers

    def login(self, app) -> str:
        status, _payload, headers = self.invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={
                "username": os.environ.get("MAVERICK_ADMIN_USERNAME", "admin"),
                "password": os.environ.get("MAVERICK_ADMIN_PASSWORD", "maverick"),
            },
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def run_backend(self, *, data_root: Path, generated_root: Path, body: dict, uploaded_root: Path | None = None) -> dict:
        return run_json_entrypoint(
            APP_ROOT / "backend" / "app_backend.py",
            payload={
                "data_root": str(data_root),
                "uploaded_storage_root": str(uploaded_root) if uploaded_root is not None else "",
                "generated_storage_root": str(generated_root),
                "body": body,
            },
            cwd=APP_ROOT,
        )

    def test_contract_declares_agent_facing_surfaces(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)

        self.assertEqual(parsed.app_id, "document-generator")
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        self.assertEqual(parsed.contract.entrypoints.frontend, "frontend/dist")
        self.assertEqual(parsed.contract.capabilities.cli_commands, ["document-generator"])
        self.assertIn("maverick_document_generator", parsed.contract.capabilities.mcp_tools)
        self.assertIn("document_generator_extract_text", parsed.contract.capabilities.mcp_tools)
        self.assertIn("document_generator_set_view_filter", parsed.contract.capabilities.mcp_tools)
        self.assertIn("document-generator-docs", parsed.contract.capabilities.skills)
        self.assertEqual(parsed.contract.capabilities.view_surfaces[0].view_id, "document-generator")
        self.assertEqual(parsed.contract.capabilities.view_surfaces[0].entity_types, ["document"])
        self.assertTrue((APP_ROOT / "frontend" / "dist" / "index.html").is_file())

    def test_backend_generates_supported_document_formats(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data_root = root / "data" / "document-generator"
            generated_root = root / "storage" / "generated"
            specs = [
                {"format": "docx", "title": "Brief", "sections": [{"heading": "Summary", "text": "Hello"}]},
                {"format": "pptx", "title": "Deck", "slides": [{"title": "Slide", "bullets": ["One"]}]},
                {"format": "pdf", "title": "PDF", "sections": [{"text": "Hello"}]},
                {"format": "xlsx", "title": "Book", "sheets": [{"name": "Sheet1", "rows": [["A", "B"], [1, 2]]}]},
            ]

            results = [
                self.run_backend(data_root=data_root, generated_root=generated_root, body={"action": "generate_document", "spec": spec})
                for spec in specs
            ]

            self.assertTrue(all(result["status_code"] == 200 for result in results))
            for result in results:
                document = result["json"]["document"]
                self.assertTrue((root / document["workspace_relative_path"]).is_file())
            self.assertTrue(zipfile.is_zipfile(generated_root / "brief.docx"))
            self.assertTrue(zipfile.is_zipfile(generated_root / "deck.pptx"))
            self.assertTrue(zipfile.is_zipfile(generated_root / "book.xlsx"))
            self.assertTrue((generated_root / "pdf.pdf").read_bytes().startswith(b"%PDF-"))

    def test_backend_extracts_text_from_supported_workspace_documents(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data_root = root / "data" / "document-generator"
            uploaded_root = root / "storage" / "uploaded"
            generated_root = root / "storage" / "generated"
            specs = [
                {"format": "docx", "title": "Brief", "sections": [{"heading": "Summary", "text": "Alpha docx text"}]},
                {"format": "pptx", "title": "Deck", "slides": [{"title": "Slide", "bullets": ["Bravo pptx text"]}]},
                {"format": "pdf", "title": "PDF", "sections": [{"heading": "Summary", "text": "Charlie pdf text"}]},
                {"format": "xlsx", "title": "Book", "sheets": [{"name": "Sheet1", "rows": [["Name", "Value"], ["Delta", "xlsx text"]]}]},
            ]
            generated = [
                self.run_backend(data_root=data_root, generated_root=generated_root, body={"action": "generate_document", "spec": spec})["json"]["document"]
                for spec in specs
            ]

            extracted = [
                self.run_backend(
                    data_root=data_root,
                    uploaded_root=uploaded_root,
                    generated_root=generated_root,
                    body={"action": "extract_text", "workspace_relative_path": document["workspace_relative_path"]},
                )["json"]
                for document in generated
            ]

            combined_text = "\n".join(item["text"] for item in extracted)
            self.assertIn("Alpha docx text", combined_text)
            self.assertIn("Bravo pptx text", combined_text)
            self.assertIn("Charlie pdf text", combined_text)
            self.assertIn("Delta", combined_text)
            self.assertIn("xlsx text", combined_text)

    def test_backend_extract_text_rejects_paths_outside_workspace_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data_root = root / "data" / "document-generator"
            generated_root = root / "storage" / "generated"

            result = self.run_backend(
                data_root=data_root,
                generated_root=generated_root,
                body={"action": "extract_text", "workspace_relative_path": "../secret.pdf"},
            )

            self.assertEqual(result["status_code"], 400)

    def test_backend_rejects_xls_and_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data_root = root / "data" / "document-generator"
            generated_root = root / "storage" / "generated"

            xls = self.run_backend(data_root=data_root, generated_root=generated_root, body={"action": "validate_spec", "spec": {"format": "xls", "title": "Old sheet"}})
            traversal = self.run_backend(data_root=data_root, generated_root=generated_root, body={"action": "generate_document", "spec": {"format": "pdf", "title": "Escape", "output_filename": "../escape.pdf"}})

            self.assertEqual(xls["status_code"], 400)
            self.assertEqual(traversal["status_code"], 400)

    @integration_test("document-generator platform integration suite; run with scripts/test_suite.py --level integration")
    def test_bootstrap_exposes_cli_mcp_and_frontend(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        tools = list_mcp_tools(app_store=state.app_store, workspace_id="default", start_path=repo_root)
        commands = list_core_cli_commands(app_store=state.app_store, workspace_id="default", start_path=repo_root)
        skills = list_available_workspace_skills(workspace_id="default", start_path=repo_root)
        frontend_status, frontend_payload, _headers = self.invoke(app, path="/apps/document-generator/", cookie=cookie)

        self.assertIn("app.document-generator.maverick_document_generator", [tool.tool_name for tool in tools])
        self.assertIn("app.document-generator.document_generator_extract_text", [tool.tool_name for tool in tools])
        self.assertIn("app.document-generator.document-generator", [command.command_id for command in commands])
        self.assertIn("document-generator-docs", [skill.skill_id for skill in skills])
        self.assertEqual(frontend_status, 200)
        self.assertIn(b"Document Generator", frontend_payload)

    @integration_test("document-generator platform integration suite; run with scripts/test_suite.py --level integration")
    def test_mcp_and_cli_generate_documents(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        spec = {"format": "xlsx", "title": "Metrics", "sheets": [{"name": "Data", "rows": [["Name", "Value"], ["A", 1]]}]}
        context = CliInvocationContext(caller_kind="sandbox_agent", workspace_id="default", agent_id="tester", effective_mode="sandbox")

        cli_payload = run_core_cli_command(
            command_id="app.document-generator.document-generator",
            context=context,
            arguments={"action": "generate_document", "spec": spec},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )
        mcp_payload = call_mcp_tool(
            tool_name="app.document-generator.maverick_document_generator",
            context=McpInvocationContext(caller_kind="sandbox_agent", workspace_id="default", agent_id="tester", effective_mode="sandbox"),
            arguments={"action": "validate_spec", "spec": spec},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )

        self.assertEqual(cli_payload["status_code"], 200)
        self.assertEqual(mcp_payload["status_code"], 200)
        self.assertTrue((repo_root / "workspaces" / "default" / cli_payload["document"]["workspace_relative_path"]).is_file())

    @integration_test("document-generator platform integration suite; run with scripts/test_suite.py --level integration")
    def test_mcp_extracts_text_from_uploaded_document(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        workspace_root = repo_root / "workspaces" / "default"
        uploaded = workspace_root / "storage" / "uploaded" / "sample" / "sample.docx"
        uploaded.parent.mkdir(parents=True, exist_ok=True)

        source_doc = run_core_cli_command(
            command_id="app.document-generator.document-generator",
            context=CliInvocationContext(caller_kind="sandbox_agent", workspace_id="default", agent_id="tester", effective_mode="sandbox"),
            arguments={
                "action": "generate_document",
                "spec": {"format": "docx", "title": "Sample", "sections": [{"heading": "Summary", "text": "Uploaded extraction text"}]},
            },
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )
        shutil.copyfile(workspace_root / source_doc["document"]["workspace_relative_path"], uploaded)

        mcp_payload = call_mcp_tool(
            tool_name="app.document-generator.document_generator_extract_text",
            context=McpInvocationContext(caller_kind="sandbox_agent", workspace_id="default", agent_id="tester", effective_mode="sandbox"),
            arguments={"workspace_relative_path": "storage/uploaded/sample/sample.docx"},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )

        self.assertEqual(mcp_payload["status_code"], 200)
        self.assertIn("Uploaded extraction text", mcp_payload["text"])


if __name__ == "__main__":
    unittest.main()
