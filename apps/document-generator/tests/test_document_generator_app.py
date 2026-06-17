"""Tests for the Document Generator app."""

from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
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

    def run_mcp(self, *, data_root: Path, generated_root: Path, tool_name: str, arguments: dict, uploaded_root: Path | None = None) -> dict:
        return run_json_entrypoint(
            APP_ROOT / "mcp" / "server.py",
            payload={
                "data_root": str(data_root),
                "uploaded_storage_root": str(uploaded_root) if uploaded_root is not None else "",
                "generated_storage_root": str(generated_root),
                "tool_name": tool_name,
                "arguments": arguments,
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
        self.assertIn("document_generator_convert_to_markdown", parsed.contract.capabilities.mcp_tools)
        self.assertIn("document_generator_extract_text", parsed.contract.capabilities.mcp_tools)
        self.assertIn("document_generator_patch_pdf_text", parsed.contract.capabilities.mcp_tools)
        self.assertIn("document_generator_modify_uploaded_document", parsed.contract.capabilities.mcp_tools)
        self.assertIn("document_generator_set_view_filter", parsed.contract.capabilities.mcp_tools)
        self.assertIn("document-generator-docs", parsed.contract.capabilities.skills)
        self.assertEqual(parsed.contract.capabilities.view_surfaces[0].view_id, "document-generator")
        self.assertEqual(parsed.contract.capabilities.view_surfaces[0].entity_types, ["document"])
        self.assertTrue((APP_ROOT / "cli" / "command_schemas.json").is_file())
        self.assertTrue((APP_ROOT / "mcp" / "tool_schemas.json").is_file())
        self.assertTrue((APP_ROOT / "frontend" / "dist" / "index.html").is_file())

    def test_descriptor_sidecars_describe_markdown_conversion_and_pdf_edits(self) -> None:
        cli_schema = json.loads((APP_ROOT / "cli" / "command_schemas.json").read_text(encoding="utf-8"))
        mcp_schema = json.loads((APP_ROOT / "mcp" / "tool_schemas.json").read_text(encoding="utf-8"))

        command_properties = cli_schema["commands"]["document-generator"]["argument_schema"]["properties"]
        tool = mcp_schema["tools"]["document_generator_convert_to_markdown"]
        patch_tool = mcp_schema["tools"]["document_generator_patch_pdf_text"]
        workflow_tool = mcp_schema["tools"]["document_generator_modify_uploaded_document"]
        tool_input_properties = tool["input_schema"]["properties"]
        tool_output_properties = tool["output_schema"]["properties"]

        self.assertIn("convert_to_markdown", command_properties["action"]["enum"])
        self.assertIn("patch_pdf_text", command_properties["action"]["enum"])
        self.assertIn("modify_uploaded_document", command_properties["action"]["enum"])
        self.assertIn("workspace_relative_path", command_properties)
        self.assertIn("patches", command_properties)
        self.assertIn("replacement_text", command_properties)
        self.assertIn("return_markdown", command_properties)
        self.assertIn("max_return_chars", command_properties)
        self.assertIn("Docling", tool["description"])
        self.assertEqual(tool["input_schema"]["required"], ["workspace_relative_path"])
        self.assertIn("workspace_relative_path", tool_input_properties)
        self.assertIn("return_markdown", tool_input_properties)
        self.assertIn("max_return_chars", tool_input_properties)
        self.assertIn("markdown_path", tool_output_properties)
        self.assertIn("manifest_path", tool_output_properties)
        self.assertIn("markdown_truncated", tool_output_properties)
        self.assertEqual(patch_tool["input_schema"]["required"], ["workspace_relative_path", "patches"])
        self.assertIn("visual_diff_artifact", patch_tool["output_schema"]["properties"])
        self.assertEqual(workflow_tool["input_schema"]["required"], ["workspace_relative_path", "replacement_text"])

    def test_dedicated_mcp_tool_action_cannot_be_overridden_by_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data_root = root / "data" / "document-generator"
            generated_root = root / "storage" / "generated"

            result = self.run_mcp(
                data_root=data_root,
                generated_root=generated_root,
                tool_name="document_generator_convert_to_markdown",
                arguments={
                    "action": "validate_spec",
                    "spec": {"format": "docx", "title": "Wrong action", "sections": []},
                },
            )

            self.assertEqual(result["status_code"], 400)
            self.assertEqual(result["error"], "validation_error")
            self.assertIn("workspace_relative_path is required", result["detail"])

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
            self.assertTrue(all(item["extraction"]["engine"] for item in extracted))

    def test_modify_uploaded_document_confirmation_does_not_emit_data_changed_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data_root = root / "data" / "document-generator"
            generated_root = root / "storage" / "generated"
            generated = self.run_backend(
                data_root=data_root,
                generated_root=generated_root,
                body={
                    "action": "generate_document",
                    "spec": {
                        "format": "pdf",
                        "title": "Two Dates",
                        "sections": [{"text": "First 18/09/2025. Second 17/06/2026."}],
                    },
                },
            )["json"]["document"]

            result = self.run_backend(
                data_root=data_root,
                generated_root=generated_root,
                body={
                    "action": "modify_uploaded_document",
                    "workspace_relative_path": generated["workspace_relative_path"],
                    "replacement_text": "18/06/2026",
                },
            )

            self.assertEqual(result["status_code"], 200)
            self.assertEqual(result["json"]["status"], "needs_confirmation")
            self.assertEqual(result["app_events"], [])

    def test_pdf_patch_match_filter_respects_case_sensitive_flag(self) -> None:
        backend_path = str(APP_ROOT / "backend")
        if backend_path not in sys.path:
            sys.path.insert(0, backend_path)
        from pdf_editor import PdfTextPatch, _find_patch_matches

        class FakePage:
            def search_for(self, _needle: str) -> list[str]:
                return ["upper-rect", "lower-rect"]

            def get_textbox(self, rect: str) -> str:
                return {"upper-rect": "Date", "lower-rect": "date"}[rect]

        class FakeDocument:
            page_count = 1

            def __getitem__(self, _page_index: int) -> FakePage:
                return FakePage()

        patch = PdfTextPatch(
            match_text="date",
            replacement_text="DATE",
            occurrence="all",
            redact_original=True,
            case_sensitive=True,
            page_number=None,
        )

        self.assertEqual(_find_patch_matches(FakeDocument(), patch), [(0, "lower-rect")])

    def test_pdf_patch_match_filter_keeps_pymupdf_matches_when_case_insensitive(self) -> None:
        backend_path = str(APP_ROOT / "backend")
        if backend_path not in sys.path:
            sys.path.insert(0, backend_path)
        from pdf_editor import PdfTextPatch, _find_patch_matches

        class FakePage:
            def search_for(self, _needle: str) -> list[str]:
                return ["upper-rect", "lower-rect"]

            def get_textbox(self, _rect: str) -> str:
                raise AssertionError("case-insensitive search should not re-check rectangles")

        class FakeDocument:
            page_count = 1

            def __getitem__(self, _page_index: int) -> FakePage:
                return FakePage()

        patch = PdfTextPatch(
            match_text="date",
            replacement_text="DATE",
            occurrence="all",
            redact_original=True,
            case_sensitive=False,
            page_number=None,
        )

        self.assertEqual(_find_patch_matches(FakeDocument(), patch), [(0, "upper-rect"), (0, "lower-rect")])

    def test_backend_patches_pdf_text_when_pymupdf_is_available(self) -> None:
        try:
            import fitz  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            self.skipTest("PyMuPDF is not installed in this test environment.")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data_root = root / "data" / "document-generator"
            uploaded_root = root / "storage" / "uploaded"
            generated_root = root / "storage" / "generated"
            source = uploaded_root / "sample.pdf"
            source.parent.mkdir(parents=True, exist_ok=True)
            generated_root.mkdir(parents=True, exist_ok=True)
            with fitz.open() as document:
                page = document.new_page()
                page.insert_text((72, 72), "Empoli, 18/09/2025", fontsize=12)
                document.save(source)

            result = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "patch_pdf_text",
                    "workspace_relative_path": "storage/uploaded/sample.pdf",
                    "patches": [
                        {
                            "match_text": "18/09/2025",
                            "replacement_text": "17/06/2026",
                            "occurrence": 1,
                            "redact_original": True,
                        }
                    ],
                    "output_filename": "sample-updated.pdf",
                },
            )

            output_path = root / result["json"]["workspace_relative_path"]
            extracted = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "extract_text", "workspace_relative_path": result["json"]["workspace_relative_path"]},
            )

            self.assertEqual(result["status_code"], 200)
            self.assertTrue(output_path.is_file())
            self.assertEqual(result["json"]["patches"][0]["old_match_count"], 1)
            self.assertEqual(result["json"]["patches"][0]["remaining_old_match_count"], 0)
            self.assertGreaterEqual(result["json"]["patches"][0]["new_match_count"], 1)
            self.assertIn("17/06/2026", extracted["json"]["text"])
            self.assertTrue((root / result["json"]["visual_diff_artifact"]).is_file())

    def test_markdown_converter_writes_docling_markdown_artifact(self) -> None:
        backend_path = str(APP_ROOT / "backend")
        if backend_path not in sys.path:
            sys.path.insert(0, backend_path)
        from markdown_converter import convert_workspace_file_to_markdown

        class FakeDoclingDocument:
            def export_to_markdown(self) -> str:
                return "# Converted Brief\n\nAgent-ready body."

        class FakeDoclingResult:
            document = FakeDoclingDocument()

        class FakeDoclingConverter:
            def convert(self, source: Path) -> FakeDoclingResult:
                self.source = source
                return FakeDoclingResult()

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data_root = root / "data" / "document-generator"
            generated_root = root / "storage" / "generated"
            source = generated_root / "source.docx"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b"docx placeholder")

            with patch("markdown_converter._load_docling_converter_class", return_value=FakeDoclingConverter), patch(
                "markdown_converter._docling_version",
                return_value="test-docling",
            ):
                result = convert_workspace_file_to_markdown(
                    data_root,
                    None,
                    generated_root,
                    {
                        "workspace_relative_path": "storage/generated/source.docx",
                        "title": "Converted Brief",
                        "output_filename": "brief.md",
                        "return_markdown": True,
                    },
                )

            document = result["document"]
            output_path = root / document["workspace_relative_path"]
            manifest_path = root / result["manifest_path"]

            self.assertEqual(document["format"], "md")
            self.assertEqual(result["markdown"], "# Converted Brief\n\nAgent-ready body.")
            self.assertFalse(result["markdown_truncated"])
            self.assertEqual(result["markdown_path"], document["workspace_relative_path"])
            self.assertTrue(output_path.is_file())
            self.assertEqual(output_path.read_text(encoding="utf-8"), "# Converted Brief\n\nAgent-ready body.\n")
            self.assertTrue(manifest_path.is_file())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["metadata"]["engine"], "docling")
            self.assertEqual(manifest["metadata"]["engine_version"], "test-docling")
            self.assertEqual(manifest["metadata"]["source_workspace_relative_path"], "storage/generated/source.docx")

    def test_markdown_converter_rejects_large_sync_sources_before_docling(self) -> None:
        backend_path = str(APP_ROOT / "backend")
        if backend_path not in sys.path:
            sys.path.insert(0, backend_path)
        from errors import DocumentValidationError
        from markdown_converter import MAX_MARKDOWN_SOURCE_FILE_BYTES, convert_workspace_file_to_markdown

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data_root = root / "data" / "document-generator"
            generated_root = root / "storage" / "generated"
            source = generated_root / "large.pdf"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b"0" * (MAX_MARKDOWN_SOURCE_FILE_BYTES + 1))

            with patch("markdown_converter._load_docling_converter_class", side_effect=AssertionError("Docling should not load")):
                with self.assertRaises(DocumentValidationError) as context:
                    convert_workspace_file_to_markdown(
                        data_root,
                        None,
                        generated_root,
                        {"workspace_relative_path": "storage/generated/large.pdf"},
                    )

            self.assertIn("10 MiB", str(context.exception))

    def test_markdown_converter_manifest_path_uses_local_app_id(self) -> None:
        backend_path = str(APP_ROOT / "backend")
        if backend_path not in sys.path:
            sys.path.insert(0, backend_path)
        from markdown_converter import convert_workspace_file_to_markdown

        class FakeDoclingDocument:
            def export_to_markdown(self) -> str:
                return "Converted body."

        class FakeDoclingResult:
            document = FakeDoclingDocument()

        class FakeDoclingConverter:
            def convert(self, source: Path) -> FakeDoclingResult:
                return FakeDoclingResult()

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            local_app_id = "document-tools"
            data_root = root / "data" / local_app_id
            generated_root = root / "storage" / "generated"
            source = generated_root / "source.pdf"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b"%PDF-1.4 placeholder")

            with patch("markdown_converter._load_docling_converter_class", return_value=FakeDoclingConverter):
                result = convert_workspace_file_to_markdown(
                    data_root,
                    None,
                    generated_root,
                    {"workspace_relative_path": "storage/generated/source.pdf"},
                    local_app_id=local_app_id,
                )

            self.assertTrue((root / result["manifest_path"]).is_file())
            self.assertTrue(result["manifest_path"].startswith(f"data/{local_app_id}/jobs/"))

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
        self.assertIn("app.document-generator.document_generator_convert_to_markdown", [tool.tool_name for tool in tools])
        self.assertIn("app.document-generator.document_generator_extract_text", [tool.tool_name for tool in tools])
        self.assertIn("app.document-generator.document-generator", [command.command_id for command in commands])
        markdown_tool = next(tool for tool in tools if tool.tool_name == "app.document-generator.document_generator_convert_to_markdown")
        document_command = next(command for command in commands if command.command_id == "app.document-generator.document-generator")
        self.assertIn("agent-ready Markdown", markdown_tool.description)
        self.assertIn("workspace_relative_path", markdown_tool.input_schema["properties"])
        self.assertIn("convert_to_markdown", document_command.argument_schema["properties"]["action"]["enum"])
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
