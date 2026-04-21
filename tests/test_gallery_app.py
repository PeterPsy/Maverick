"""Tests for the native Gallery app."""

from __future__ import annotations

from io import BytesIO
import json
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


REPO_ROOT = Path(__file__).resolve().parents[1]
GALLERY_ROOT = REPO_ROOT / "apps" / "gallery"


class GalleryAppTestCase(unittest.TestCase):
    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick-v3"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        (repo_root / "IMPLEMENTATION_TASKLIST.md").write_text("", encoding="utf-8")
        source_apps_root = REPO_ROOT / "apps"
        for app_id in ("base-shell", "chat", "gallery"):
            shutil.copytree(
                source_apps_root / app_id,
                repo_root / "apps" / app_id,
                ignore=shutil.ignore_patterns("node_modules", "__pycache__"),
            )
        return repo_root

    def invoke(
        self,
        app,
        *,
        path: str,
        method: str = "GET",
        body: dict | None = None,
        cookie: str | None = None,
        query_string: str = "",
    ) -> tuple[int, dict | bytes, dict[str, str]]:
        payload = b"" if body is None else json.dumps(body).encode("utf-8")
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(payload)),
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": query_string,
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

    def run_backend(self, *, data_root: Path, uploaded_root: Path, generated_root: Path, body: dict) -> dict:
        return run_json_entrypoint(
            GALLERY_ROOT / "backend" / "app_backend.py",
            payload={
                "data_root": str(data_root),
                "uploaded_storage_root": str(uploaded_root),
                "generated_storage_root": str(generated_root),
                "body": body,
            },
            cwd=GALLERY_ROOT,
        )

    def test_contract_declares_gallery_surfaces(self) -> None:
        parsed = parse_app_contract_file(GALLERY_ROOT)

        self.assertEqual(parsed.app_id, "gallery")
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        self.assertEqual(parsed.contract.entrypoints.frontend, "frontend/dist")
        self.assertIn("maverick_gallery", parsed.contract.capabilities.mcp_tools)
        self.assertIn("gallery_reference_manifest", parsed.contract.capabilities.mcp_tools)
        self.assertEqual(parsed.contract.capabilities.cli_commands, ["gallery"])
        self.assertEqual(parsed.contract.capabilities.skills, [])
        self.assertIn("file", {item.entity_type for item in parsed.contract.capabilities.reference_entities})
        self.assertEqual(len(parsed.contract.widgets), 1)
        widget = parsed.contract.widgets[0]
        self.assertEqual(widget.widget_id, "file-preview")
        self.assertEqual(widget.host, "chat")
        self.assertIn("gallery.file.preview", widget.content_kinds)
        self.assertEqual(widget.frontend.mount, "frontend/dist/widgets/file-preview")
        self.assertTrue((GALLERY_ROOT / "frontend" / "dist" / "widgets" / "file-preview" / "index.html").is_file())

    def test_backend_catalog_derives_uploaded_and_generated_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            uploaded_root = root / "storage" / "uploaded"
            generated_root = root / "storage" / "generated"
            data_root = root / "data" / "gallery"
            (uploaded_root / "file-1").mkdir(parents=True)
            generated_root.mkdir(parents=True)
            (uploaded_root / "file-1" / "brief.txt").write_text("brief", encoding="utf-8")
            (generated_root / "report.md").write_text("# report", encoding="utf-8")
            (generated_root / "deck.pptx").write_bytes(b"deck")
            (generated_root / "clip.mp4").write_bytes(b"video")

            result = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "catalog"},
            )

            self.assertEqual(result["status_code"], 200)
            paths = {item["workspace_relative_path"] for item in result["json"]["files"]}
            self.assertEqual(
                paths,
                {
                    "storage/uploaded/file-1/brief.txt",
                    "storage/generated/report.md",
                    "storage/generated/deck.pptx",
                    "storage/generated/clip.mp4",
                },
            )
            kinds = {item["workspace_relative_path"]: item["preview_kind"] for item in result["json"]["files"]}
            self.assertEqual(kinds["storage/generated/report.md"], "markdown")
            self.assertEqual(kinds["storage/generated/deck.pptx"], "presentation")
            self.assertEqual(kinds["storage/generated/clip.mp4"], "video")

    def test_backend_persists_view_filter_for_shared_ui_control(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data_root = root / "data" / "gallery"
            uploaded_root = root / "storage" / "uploaded"
            generated_root = root / "storage" / "generated"

            updated = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "set_view_filter", "query": "Versy", "role": "generated", "kind": "document"},
            )
            catalog = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "catalog"},
            )
            rejected = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "set_view_filter", "kind": "unknown"},
            )

            self.assertEqual(updated["status_code"], 200)
            self.assertEqual(catalog["json"]["state"]["view_filter"]["query"], "Versy")
            self.assertEqual(catalog["json"]["state"]["view_filter"]["role"], "generated")
            self.assertEqual(catalog["json"]["state"]["view_filter"]["kind"], "document")
            self.assertTrue(catalog["json"]["state"]["view_filter"]["updated_at"])
            self.assertEqual(rejected["status_code"], 400)

    def test_backend_rejects_path_traversal_when_reading_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self.run_backend(
                data_root=root / "data" / "gallery",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=root / "storage" / "generated",
                body={"action": "read_file", "role": "generated", "relative_path": "../secret.txt"},
            )

            self.assertEqual(result["status_code"], 400)
            self.assertEqual(result["json"]["error"], "validation_error")

    def test_backend_reads_file_reference_from_workspace_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            generated_root.mkdir(parents=True)
            (generated_root / "report.md").write_text("# report", encoding="utf-8")

            info = self.run_backend(
                data_root=root / "data" / "gallery",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "file_info", "workspace_relative_path": "storage/generated/report.md"},
            )
            preview = self.run_backend(
                data_root=root / "data" / "gallery",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "read_file", "workspace_relative_path": "storage/generated/report.md"},
            )

            self.assertEqual(info["status_code"], 200)
            self.assertEqual(info["json"]["file"]["relative_path"], "report.md")
            self.assertEqual(preview["status_code"], 200)
            self.assertEqual(preview["json"]["file"]["preview_kind"], "markdown")

    def test_backend_renames_file_inside_same_storage_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            generated_root.mkdir(parents=True)
            (generated_root / "report.md").write_text("# report", encoding="utf-8")

            renamed = self.run_backend(
                data_root=root / "data" / "gallery",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={
                    "action": "rename_file",
                    "role": "generated",
                    "relative_path": "report.md",
                    "new_name": "final-report.md",
                },
            )
            rejected = self.run_backend(
                data_root=root / "data" / "gallery",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={
                    "action": "rename_file",
                    "role": "generated",
                    "relative_path": "final-report.md",
                    "new_name": "../escape.md",
                },
            )

            self.assertEqual(renamed["status_code"], 200)
            self.assertEqual(renamed["json"]["file"]["workspace_relative_path"], "storage/generated/final-report.md")
            self.assertTrue((generated_root / "final-report.md").is_file())
            self.assertFalse((generated_root / "report.md").exists())
            self.assertEqual(rejected["status_code"], 400)

    def test_backend_deletes_file_inside_workspace_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            generated_root.mkdir(parents=True)
            target = generated_root / "report.md"
            target.write_text("# report", encoding="utf-8")

            deleted = self.run_backend(
                data_root=root / "data" / "gallery",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "delete_file", "workspace_relative_path": "storage/generated/report.md"},
            )
            rejected = self.run_backend(
                data_root=root / "data" / "gallery",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "delete_file", "role": "generated", "relative_path": "../secret.txt"},
            )

            self.assertEqual(deleted["status_code"], 200)
            self.assertTrue(deleted["json"]["deleted"])
            self.assertEqual(deleted["json"]["file"]["workspace_relative_path"], "storage/generated/report.md")
            self.assertFalse(target.exists())
            self.assertEqual(rejected["status_code"], 400)

    def test_backend_extracts_office_preview_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            generated_root.mkdir(parents=True)
            docx = generated_root / "brief.docx"
            with zipfile.ZipFile(docx, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    """<?xml version="1.0" encoding="UTF-8"?>
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                      <w:body><w:p><w:r><w:t>Quarterly brief</w:t></w:r></w:p></w:body>
                    </w:document>""",
                )

            preview = self.run_backend(
                data_root=root / "data" / "gallery",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "preview_text", "workspace_relative_path": "storage/generated/brief.docx"},
            )
            cached_preview = self.run_backend(
                data_root=root / "data" / "gallery",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "preview_text", "workspace_relative_path": "storage/generated/brief.docx"},
            )

            self.assertEqual(preview["status_code"], 200)
            self.assertEqual(preview["json"]["file"]["preview_kind"], "document")
            self.assertIn("Quarterly brief", preview["json"]["preview_text"])
            self.assertFalse(preview["json"]["cache_hit"])
            self.assertTrue(cached_preview["json"]["cache_hit"])

    def test_bootstrap_installs_gallery_and_exposes_surfaces(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        bindings = state.app_store.list_workspace_app_bindings("default")
        self.assertIn("gallery", {binding.app_id for binding in bindings})
        self.assertTrue((repo_root / "workspaces" / "default" / "data" / "gallery" / "state.json").is_file())

        tools = list_mcp_tools(app_store=state.app_store, workspace_id="default", start_path=repo_root)
        commands = list_core_cli_commands(app_store=state.app_store, workspace_id="default", start_path=repo_root)

        self.assertIn("app.gallery.maverick_gallery", [tool.tool_name for tool in tools])
        self.assertIn("app.gallery.gallery", [command.command_id for command in commands])

    def test_platform_backend_and_frontend_mount_gallery(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        generated = repo_root / "workspaces" / "default" / "storage" / "generated" / "report.txt"
        generated.parent.mkdir(parents=True, exist_ok=True)
        generated.write_text("hello", encoding="utf-8")

        backend_status, backend_payload, _backend_headers = self.invoke(
            app,
            path="/api/apps/gallery/backend",
            method="POST",
            body={"action": "catalog"},
        )
        frontend_status, frontend_payload, frontend_headers = self.invoke(app, path="/apps/gallery/")

        self.assertEqual(backend_status, 200)
        self.assertEqual(backend_payload["files"][0]["workspace_relative_path"], "storage/generated/report.txt")
        self.assertEqual(frontend_status, 200)
        self.assertIn("text/html", frontend_headers["Content-Type"])
        self.assertIn(b"Maverick Gallery", frontend_payload)

    def test_mcp_and_cli_call_gallery_catalog(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        uploaded = repo_root / "workspaces" / "default" / "storage" / "uploaded" / "source.txt"
        uploaded.parent.mkdir(parents=True, exist_ok=True)
        uploaded.write_text("source", encoding="utf-8")

        mcp_payload = call_mcp_tool(
            tool_name="app.gallery.maverick_gallery",
            context=McpInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id="tester",
                effective_mode="sandbox",
            ),
            arguments={"action": "catalog"},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )
        cli_payload = run_core_cli_command(
            command_id="app.gallery.gallery",
            context=CliInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id="tester",
                effective_mode="sandbox",
            ),
            arguments={"action": "catalog"},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )

        self.assertEqual(mcp_payload["status_code"], 200)
        self.assertEqual(cli_payload["status_code"], 200)
        self.assertEqual(mcp_payload["files"][0]["workspace_relative_path"], "storage/uploaded/source.txt")
        self.assertEqual(cli_payload["files"][0]["workspace_relative_path"], "storage/uploaded/source.txt")

    def test_cli_can_update_gallery_view_filter(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        updated = run_core_cli_command(
            command_id="app.gallery.gallery",
            context=CliInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id="tester",
                effective_mode="sandbox",
            ),
            arguments={"action": "set_view_filter", "query": "Versy", "role": "generated", "kind": "document"},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )
        catalog = run_core_cli_command(
            command_id="app.gallery.gallery",
            context=CliInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id="tester",
                effective_mode="sandbox",
            ),
            arguments={"action": "catalog"},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )

        self.assertEqual(updated["status_code"], 200)
        self.assertEqual(catalog["state"]["view_filter"]["query"], "Versy")
        self.assertEqual(catalog["state"]["view_filter"]["role"], "generated")
        self.assertEqual(catalog["state"]["view_filter"]["kind"], "document")

    def test_cli_can_read_gallery_view_filter_without_catalog_scan(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        run_core_cli_command(
            command_id="app.gallery.gallery",
            context=CliInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id="tester",
                effective_mode="sandbox",
            ),
            arguments={"action": "set_view_filter", "query": "Versy"},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )
        view_filter = run_core_cli_command(
            command_id="app.gallery.gallery",
            context=CliInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id="tester",
                effective_mode="sandbox",
            ),
            arguments={"action": "view_filter"},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )

        self.assertEqual(view_filter["status_code"], 200)
        self.assertEqual(view_filter["state"]["view_filter"]["query"], "Versy")
        self.assertNotIn("files", view_filter)


if __name__ == "__main__":
    unittest.main()
