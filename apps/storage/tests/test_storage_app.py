"""Tests for the native Storage app."""

from __future__ import annotations

from base64 import b64decode, b64encode
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
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
from tests.support.markers import full_test, integration_test


REPO_ROOT = Path(__file__).resolve().parents[3]
STORAGE_ROOT = REPO_ROOT / "apps" / "storage"


class StorageAppTestCase(unittest.TestCase):
    def storage_cli_argument_schema(self) -> dict:
        descriptor = json.loads((STORAGE_ROOT / "cli" / "command_schemas.json").read_text(encoding="utf-8"))
        return descriptor["commands"]["storage"]["argument_schema"]

    def schema_accepts_payload(self, schema: dict, payload: dict) -> bool:
        if "maxProperties" in schema and len(payload) > int(schema["maxProperties"]):
            return False
        if any(field not in payload for field in schema.get("required", [])):
            return False
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra_fields = set(payload) - set(properties)
            if extra_fields:
                return False
        for field, field_schema in properties.items():
            if field in payload and "enum" in field_schema and payload[field] not in field_schema["enum"]:
                return False
            if field in payload and "minItems" in field_schema:
                if not isinstance(payload[field], list) or len(payload[field]) < int(field_schema["minItems"]):
                    return False
        if "anyOf" in schema and not any(self.schema_accepts_payload(option, payload) for option in schema["anyOf"]):
            return False
        if "oneOf" in schema:
            matches = sum(1 for option in schema["oneOf"] if self.schema_accepts_payload(option, payload))
            if matches != 1:
                return False
        return True

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        shutil.copy2(REPO_ROOT / "core" / "__init__.py", repo_root / "core" / "__init__.py")
        shutil.copytree(
            REPO_ROOT / "core" / "app_sdk",
            repo_root / "core" / "app_sdk",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        source_apps_root = REPO_ROOT / "apps"
        for app_id in ("base-shell", "chat", "storage"):
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
        extra_headers: dict[str, str] | None = None,
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
        if extra_headers:
            environ.update(extra_headers)

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

    def run_backend(self, *, data_root: Path, uploaded_root: Path, generated_root: Path, body: dict) -> dict:
        return run_json_entrypoint(
            STORAGE_ROOT / "backend" / "app_backend.py",
            payload={
                "data_root": str(data_root),
                "uploaded_storage_root": str(uploaded_root),
                "generated_storage_root": str(generated_root),
                "body": body,
            },
            cwd=STORAGE_ROOT,
        )

    def run_cli(
        self,
        *,
        data_root: Path,
        uploaded_root: Path,
        generated_root: Path,
        arguments: dict,
        workspace_root: Path | None = None,
        effective_mode: str = "sandbox",
    ) -> dict:
        resolved_workspace_root = workspace_root if workspace_root is not None else data_root.parents[1]
        return run_json_entrypoint(
            STORAGE_ROOT / "cli" / "app_cli.py",
            payload={
                "workspace_id": "default",
                "data_root": str(data_root),
                "workspace_root": str(resolved_workspace_root),
                "uploaded_storage_root": str(uploaded_root),
                "generated_storage_root": str(generated_root),
                "effective_mode": effective_mode,
                "arguments": arguments,
                "surface": "cli",
            },
            cwd=STORAGE_ROOT,
        )

    def test_contract_declares_storage_surfaces(self) -> None:
        parsed = parse_app_contract_file(STORAGE_ROOT)

        self.assertEqual(parsed.app_id, "storage")
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        self.assertEqual(parsed.contract.entrypoints.frontend, "frontend/dist")
        self.assertIn("maverick_storage", parsed.contract.capabilities.mcp_tools)
        self.assertIn("storage_list_files", parsed.contract.capabilities.mcp_tools)
        self.assertIn("storage_read_file", parsed.contract.capabilities.mcp_tools)
        self.assertIn("storage_read_text", parsed.contract.capabilities.mcp_tools)
        self.assertIn("storage_preview_text", parsed.contract.capabilities.mcp_tools)
        self.assertIn("storage_set_view_filter", parsed.contract.capabilities.mcp_tools)
        self.assertIn("storage_reference_manifest", parsed.contract.capabilities.mcp_tools)
        self.assertIn("storage_write_file", parsed.contract.capabilities.mcp_tools)
        self.assertIn("storage_image_inspect", parsed.contract.capabilities.mcp_tools)
        self.assertIn("storage_image_compose_pair", parsed.contract.capabilities.mcp_tools)
        self.assertIn("storage_drive_list_roots", parsed.contract.capabilities.mcp_tools)
        self.assertIn("storage_drive_list_children", parsed.contract.capabilities.mcp_tools)
        self.assertIn("storage_drive_search", parsed.contract.capabilities.mcp_tools)
        self.assertIn("storage_file_localize", parsed.contract.capabilities.mcp_tools)
        self.assertNotIn("storage_file_media_stream", parsed.contract.capabilities.mcp_tools)
        self.assertEqual(parsed.contract.capabilities.cli_commands, ["storage"])
        self.assertEqual(parsed.contract.capabilities.skills, ["storage-ops"])
        provided_interfaces = {item.interface for item in parsed.contract.provides}
        self.assertIn("file.text.read", provided_interfaces)
        self.assertIn("file.content.write", provided_interfaces)
        self.assertIn("file.image.ops", provided_interfaces)
        self.assertIn("file.media.stream", provided_interfaces)
        media_interface = next(item for item in parsed.contract.provides if item.interface == "file.media.stream")
        self.assertEqual(media_interface.surfaces, ["backend", "view", "widget"])
        reference_entity_types = {item.entity_type for item in parsed.contract.capabilities.reference_entities}
        self.assertIn("file", reference_entity_types)
        self.assertIn("folder", reference_entity_types)
        self.assertEqual(parsed.contract.capabilities.view_surfaces[0].view_id, "storage")
        self.assertEqual(parsed.contract.capabilities.view_surfaces[0].entity_types, ["file"])
        view_actions = {
            item.action: item
            for item in parsed.contract.capabilities.view_surfaces[0].state_actions
        }
        self.assertTrue(view_actions["set_custom_view"].standard)
        self.assertTrue(view_actions["set_view_filter"].standard)
        self.assertTrue(parsed.contract.capabilities.view_surfaces[0].supports_custom_view)
        self.assertEqual(len(parsed.contract.widgets), 3)
        widgets = {widget.widget_id: widget for widget in parsed.contract.widgets}
        sidebar_widget = widgets["storage-sidebar"]
        self.assertEqual(sidebar_widget.host, "base-shell")
        self.assertEqual(sidebar_widget.content_kinds, ["shell.sidebar.primary"])
        self.assertEqual(sidebar_widget.frontend.mount, "frontend/dist/widgets/storage-sidebar")
        self.assertTrue((STORAGE_ROOT / "frontend" / "dist" / "widgets" / "storage-sidebar" / "index.html").is_file())
        footer_widget = widgets["storage-sidebar-footer"]
        self.assertEqual(footer_widget.host, "base-shell")
        self.assertEqual(footer_widget.content_kinds, ["shell.sidebar.footer"])
        self.assertEqual(footer_widget.frontend.mount, "frontend/dist/widgets/storage-sidebar-footer")
        self.assertTrue((STORAGE_ROOT / "frontend" / "dist" / "widgets" / "storage-sidebar-footer" / "index.html").is_file())
        widget = widgets["file-preview"]
        self.assertEqual(widget.host, "chat")
        self.assertIn("storage.file.preview", widget.content_kinds)
        self.assertEqual(widget.frontend.mount, "frontend/dist/widgets/file-preview")
        self.assertTrue((STORAGE_ROOT / "frontend" / "dist" / "widgets" / "file-preview" / "index.html").is_file())

    def test_backend_catalog_derives_uploaded_and_generated_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            uploaded_root = root / "storage" / "uploaded"
            generated_root = root / "storage" / "generated"
            data_root = root / "data" / "storage"
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
            self.assertEqual(result["json"]["available_kinds"], ["video", "presentation", "markdown", "text"])

    def test_backend_catalog_keeps_local_records_provider_aware(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            uploaded_root = root / "storage" / "uploaded"
            generated_root = root / "storage" / "generated"
            uploaded_root.mkdir(parents=True)
            generated_root.mkdir(parents=True)
            (uploaded_root / "brief.txt").write_text("brief", encoding="utf-8")
            (generated_root / "report.md").write_text("# report", encoding="utf-8")

            result = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "catalog"},
            )

            self.assertEqual(result["status_code"], 200)
            by_path = {item["workspace_relative_path"]: item for item in result["json"]["files"]}
            self.assertEqual(set(by_path), {"storage/uploaded/brief.txt", "storage/generated/report.md"})
            for item in by_path.values():
                self.assertEqual(item["provider"], "local")
                self.assertIn(item["role"], {"uploaded", "generated"})
                self.assertEqual(item["connection_id"], "")
                self.assertEqual(item["drive_file_id"], "")
                self.assertEqual(item["remote_locator"], {})
                self.assertEqual(item["display_path"], item["workspace_relative_path"])
                self.assertEqual(item["sync_status"], "synced")
                self.assertFalse(item["indexed"])
                self.assertFalse(item["stale"])
                self.assertTrue(item["capabilities"]["can_read"])
                self.assertTrue(item["capabilities"]["can_write"])

    def test_image_inspect_and_compose_pair_writes_generated_image(self) -> None:
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            self.skipTest("ffmpeg and ffprobe are required for Storage image operations")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            uploaded_root = root / "storage" / "uploaded"
            generated_root = root / "storage" / "generated"
            data_root = root / "data" / "storage"
            generated_root.mkdir(parents=True)
            front = generated_root / "id-front.png"
            back = generated_root / "id-back.png"
            for path, size, color in ((front, "120x80", "red"), (back, "100x80", "blue")):
                subprocess.run(
                    [
                        ffmpeg,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-f",
                        "lavfi",
                        "-i",
                        f"color=c={color}:s={size}:d=0.1",
                        "-frames:v",
                        "1",
                        str(path),
                    ],
                    check=True,
                    timeout=20,
                )

            inspected = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "image.inspect",
                    "workspace_relative_paths": ["storage/generated/id-front.png", "storage/generated/id-back.png"],
                },
            )

            self.assertEqual(inspected["status_code"], 200, inspected)
            self.assertEqual(inspected["json"]["image_count"], 2)
            self.assertEqual(inspected["json"]["images"][0]["display_height"], 80)
            self.assertNotIn("local_path", inspected["json"]["images"][0])

            composed = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "image.compose_pair",
                    "images": ["storage/generated/id-front.png", "storage/generated/id-back.png"],
                    "target_folder": "documents",
                    "file_name": "id-card.jpg",
                    "height": 60,
                    "mode": "create",
                },
            )

            self.assertEqual(composed["status_code"], 200, composed)
            payload = composed["json"]
            self.assertEqual(payload["workspace_relative_path"], "storage/generated/documents/id-card.jpg")
            self.assertTrue((generated_root / "documents" / "id-card.jpg").is_file())
            self.assertEqual(payload["file"]["preview_kind"], "image")
            self.assertEqual(payload["output_image"]["display_height"], 60)
            self.assertEqual(len(payload["source_images"]), 2)
            self.assertNotIn("local_path", payload["source_images"][0])

    def test_backend_catalog_preserves_remote_provider_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data_root = root / "data" / "storage"
            data_root.mkdir(parents=True)
            remote_id = "file_0123456789abcdef0123456789abcdef"
            (data_root / "files.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "files": [
                            {
                                "id": remote_id,
                                "provider": "google_drive",
                                "connection_id": "drive_conn_123",
                                "drive_file_id": "drive_file_123",
                                "remote_locator": {"drive_file_id": "drive_file_123"},
                                "display_path": "/Clienti/Acme/Contratto.pdf",
                                "name": "Contratto.pdf",
                                "content_type": "application/pdf",
                                "preview_kind": "pdf",
                                "capabilities": {"can_read": True, "can_index": True},
                                "sync_status": "synced",
                                "indexed": True,
                                "stale": False,
                                "status": "active",
                            }
                        ],
                        "directories": [],
                        "updated_at": "",
                    }
                ),
                encoding="utf-8",
            )

            catalog = self.run_backend(
                data_root=data_root,
                uploaded_root=root / "storage" / "uploaded",
                generated_root=root / "storage" / "generated",
                body={"action": "catalog", "file_ids": [remote_id]},
            )

            self.assertEqual(catalog["status_code"], 200)
            self.assertEqual(len(catalog["json"]["files"]), 1)
            file_record = catalog["json"]["files"][0]
            self.assertEqual(file_record["id"], remote_id)
            self.assertEqual(file_record["provider"], "google_drive")
            self.assertEqual(file_record["connection_id"], "drive_conn_123")
            self.assertEqual(file_record["drive_file_id"], "drive_file_123")
            self.assertEqual(file_record["workspace_relative_path"], "")
            self.assertEqual(file_record["role"], "")
            self.assertTrue(file_record["capabilities"]["can_read"])
            self.assertTrue(file_record["indexed"])
            self.assertFalse(file_record["stale"])

    def test_backend_catalog_orders_newest_files_first_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            uploaded_root = root / "storage" / "uploaded"
            generated_root = root / "storage" / "generated"
            data_root = root / "data" / "storage"
            uploaded_root.mkdir(parents=True)
            generated_root.mkdir(parents=True)
            older = uploaded_root / "brief.txt"
            newest = generated_root / "report.md"
            tie_a = generated_root / "a.txt"
            tie_b = generated_root / "b.txt"
            older.write_text("brief", encoding="utf-8")
            newest.write_text("# report", encoding="utf-8")
            tie_a.write_text("a", encoding="utf-8")
            tie_b.write_text("b", encoding="utf-8")
            os.utime(older, (100, 100))
            os.utime(tie_b, (200, 200))
            os.utime(tie_a, (200, 200))
            os.utime(newest, (300, 300))

            result = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "catalog"},
            )

            self.assertEqual(result["status_code"], 200)
            self.assertEqual(
                [item["workspace_relative_path"] for item in result["json"]["files"]],
                [
                    "storage/generated/report.md",
                    "storage/generated/a.txt",
                    "storage/generated/b.txt",
                    "storage/uploaded/brief.txt",
                ],
            )

    def test_backend_catalog_lists_empty_folders(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            uploaded_root = root / "storage" / "uploaded"
            generated_root = root / "storage" / "generated"
            data_root = root / "data" / "storage"
            (generated_root / "reports" / "q1").mkdir(parents=True)
            uploaded_bucket = uploaded_root / "834cd104-3247-422b-8669-bf5787df25d8"
            uploaded_bucket.mkdir(parents=True)
            (uploaded_bucket / "image.png").write_bytes(b"png")
            (uploaded_root / "Client Docs").mkdir(parents=True)

            result = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "catalog"},
            )

            self.assertEqual(result["status_code"], 200)
            folder_paths = {item["workspace_relative_path"] for item in result["json"]["folders"]}
            self.assertEqual(folder_paths, {"storage/generated/reports", "storage/generated/reports/q1", "storage/uploaded/Client Docs"})
            file_paths = {item["workspace_relative_path"] for item in result["json"]["files"]}
            self.assertIn("storage/uploaded/834cd104-3247-422b-8669-bf5787df25d8/image.png", file_paths)

    def test_backend_catalog_discovers_out_of_band_files_after_inventory_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            generated_root.mkdir(parents=True)
            (generated_root / "first.md").write_text("# first", encoding="utf-8")

            initial = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "catalog"},
            )
            (generated_root / "second.md").write_text("# second", encoding="utf-8")
            (generated_root / "Empty").mkdir()
            catalog = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "catalog"},
            )
            search = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "references.search", "query": "second"},
            )

            self.assertEqual(initial["status_code"], 200)
            self.assertEqual(catalog["status_code"], 200)
            self.assertIn("storage/generated/second.md", {item["workspace_relative_path"] for item in catalog["json"]["files"]})
            self.assertIn("storage/generated/Empty", {item["workspace_relative_path"] for item in catalog["json"]["folders"]})
            self.assertEqual(search["json"]["results"][0]["workspace_relative_path"], "storage/generated/second.md")

    def test_backend_reference_search_ranks_exact_storage_file_matches_before_recency(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            uploaded_root = root / "storage" / "uploaded"
            generated_root = root / "storage" / "generated"
            exact_parent = generated_root / "Client Docs"
            exact_parent.mkdir(parents=True)
            uploaded_root.mkdir(parents=True)
            exact = exact_parent / "contract.pdf"
            noisy = generated_root / "zz-contract.pdf"
            exact.write_bytes(b"%PDF exact")
            noisy.write_bytes(b"%PDF noisy")
            os.utime(exact, (1_700_000_000, 1_700_000_000))
            os.utime(noisy, (1_800_000_000, 1_800_000_000))

            by_name = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "references.search", "query": "contract.pdf", "limit": 1},
            )
            by_path = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "references.search", "query": "storage/generated/Client Docs/contract.pdf", "limit": 1},
            )

            self.assertEqual(by_name["status_code"], 200)
            self.assertEqual(by_path["status_code"], 200)
            self.assertEqual(by_name["json"]["results"][0]["workspace_relative_path"], "storage/generated/Client Docs/contract.pdf")
            self.assertEqual(by_path["json"]["results"][0]["workspace_relative_path"], "storage/generated/Client Docs/contract.pdf")
            self.assertIn("storage/generated/Client Docs/contract.pdf", by_name["json"]["results"][0]["summary"])

    def test_backend_reference_search_resolves_storage_folders(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            uploaded_root = root / "storage" / "uploaded"
            generated_root = root / "storage" / "generated"
            data_root = root / "data" / "storage"
            (generated_root / "Client Docs" / "Q1").mkdir(parents=True)
            (generated_root / "Client Docs" / "Q1" / "brief.txt").write_text("brief", encoding="utf-8")
            (uploaded_root / "Receipts").mkdir(parents=True)
            hidden_bucket = uploaded_root / "834cd104-3247-422b-8669-bf5787df25d8"
            hidden_bucket.mkdir(parents=True)

            search = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "references.search", "entity_type": "folder", "query": "q1", "limit": 5},
            )
            root_search = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "references.search", "entity_type": "folder", "query": "generated", "limit": 5},
            )
            resolved = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "references.resolve", "entity_type": "folder", "entity_id": "generated:Client%20Docs/Q1/"},
            )
            summarized = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "references.summarize", "entity_type": "folder", "entity_id": "generated:Client%20Docs/Q1/"},
            )
            hidden = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "references.resolve",
                    "entity_type": "folder",
                    "entity_id": "uploaded:834cd104-3247-422b-8669-bf5787df25d8/",
                },
            )

            self.assertEqual(search["status_code"], 200)
            self.assertEqual(search["json"]["results"][0]["entity_type"], "folder")
            self.assertEqual(search["json"]["results"][0]["entity_id"], "generated:Client%20Docs/Q1/")
            self.assertEqual(search["json"]["results"][0]["workspace_relative_path"], "storage/generated/Client Docs/Q1")
            self.assertEqual(search["json"]["results"][0]["deep_link"], "/app/storage/folders/generated/Client%20Docs/Q1")
            self.assertEqual(root_search["json"]["results"][0]["workspace_relative_path"], "storage/generated")
            self.assertTrue(resolved["json"]["exists"])
            self.assertEqual(resolved["json"]["title"], "Q1")
            self.assertEqual(summarized["json"]["safe_fields"]["kind"], "folder")
            self.assertFalse(hidden["json"]["exists"])

    def test_backend_catalog_handles_legacy_inventory_and_skips_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data_root = root / "data" / "storage"
            generated_root = root / "storage" / "generated"
            data_root.mkdir(parents=True)
            generated_root.mkdir(parents=True)
            (data_root / "files.json").write_text(json.dumps({"schema_version": "1", "files": [], "updated_at": ""}), encoding="utf-8")
            (generated_root / "report.md").write_text("# Report", encoding="utf-8")
            (generated_root / ".maverick-storage-write-report.md.partial.tmp").write_text("partial", encoding="utf-8")
            (generated_root / ".cache.tmp").write_text("user temp", encoding="utf-8")

            catalog = self.run_backend(
                data_root=data_root,
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "catalog"},
            )
            health = self.run_backend(
                data_root=data_root,
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "health.check"},
            )

            self.assertEqual(catalog["status_code"], 200)
            self.assertEqual(health["status_code"], 200)
            workspace_paths = {item["workspace_relative_path"] for item in catalog["json"]["files"]}
            self.assertIn("storage/generated/report.md", workspace_paths)
            self.assertIn("storage/generated/.cache.tmp", workspace_paths)
            self.assertNotIn("storage/generated/.maverick-storage-write-report.md.partial.tmp", workspace_paths)

    def test_backend_health_check_does_not_refresh_file_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data_root = root / "data" / "storage"
            generated_root = root / "storage" / "generated"
            generated_root.mkdir(parents=True)
            (generated_root / "report.md").write_text("# Report", encoding="utf-8")

            health = self.run_backend(
                data_root=data_root,
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "health.check"},
            )

            self.assertEqual(health["status_code"], 200)
            self.assertEqual(health["json"]["status"], "ok")
            self.assertFalse((data_root / "files.json").exists())

    def test_backend_persists_view_filter_for_shared_ui_control(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data_root = root / "data" / "storage"
            uploaded_root = root / "storage" / "uploaded"
            generated_root = root / "storage" / "generated"

            updated = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "set_view_filter", "query": "Acme", "role": "generated", "kind": "document"},
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
            self.assertEqual(catalog["json"]["state"]["view_filter"]["query"], "Acme")
            self.assertEqual(catalog["json"]["state"]["view_filter"]["role"], "generated")
            self.assertEqual(catalog["json"]["state"]["view_filter"]["kind"], "document")
            self.assertTrue(catalog["json"]["state"]["view_filter"]["updated_at"])
            self.assertEqual(rejected["status_code"], 400)

    def test_backend_persists_custom_view_for_explicit_file_sets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data_root = root / "data" / "storage"
            uploaded_root = root / "storage" / "uploaded"
            generated_root = root / "storage" / "generated"

            custom = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "set_custom_view",
                    "title": "Topic: Acme",
                    "file_ids": ["generated:company_profile.docx"],
                    "workspace_relative_paths": ["storage/uploaded/logo/Logo.png"],
                },
            )
            refined = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "set_view_filter", "query": "deck", "preserve_custom": True},
            )
            cleared = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "clear_custom_view"},
            )
            rejected = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "set_custom_view", "file_ids": ["generated:../secret.txt"]},
            )

            self.assertEqual(custom["status_code"], 200)
            view = custom["json"]["state"]["view_filter"]
            self.assertEqual(view["mode"], "custom")
            self.assertEqual(view["title"], "Topic: Acme")
            self.assertEqual(view["file_ids"], ["generated:company_profile.docx"])
            self.assertEqual(view["workspace_relative_paths"], ["storage/uploaded/logo/Logo.png"])
            self.assertEqual(refined["json"]["state"]["view_filter"]["mode"], "custom")
            self.assertEqual(refined["json"]["state"]["view_filter"]["query"], "deck")
            self.assertEqual(cleared["json"]["state"]["view_filter"]["mode"], "search")
            self.assertEqual(rejected["status_code"], 400)

    def test_backend_rejects_path_traversal_when_reading_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self.run_backend(
                data_root=root / "data" / "storage",
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
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "file_info", "workspace_relative_path": "storage/generated/report.md"},
            )
            preview = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "read_file", "workspace_relative_path": "storage/generated/report.md"},
            )

            self.assertEqual(info["status_code"], 200)
            self.assertEqual(info["json"]["file"]["relative_path"], "report.md")
            self.assertEqual(preview["status_code"], 200)
            self.assertEqual(preview["json"]["file"]["preview_kind"], "markdown")

    def test_backend_file_info_resolves_stable_file_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            generated_root.mkdir(parents=True)
            (generated_root / "report.md").write_text("# report", encoding="utf-8")

            catalog = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "catalog"},
            )
            file_id = catalog["json"]["files"][0]["id"]
            info = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "file_info", "file_id": file_id},
            )

            self.assertEqual(info["status_code"], 200)
            self.assertEqual(info["json"]["file"]["id"], file_id)
            self.assertEqual(info["json"]["file"]["workspace_relative_path"], "storage/generated/report.md")
            self.assertEqual(info["json"]["file"]["provider"], "local")

    def test_backend_rejects_workspace_relative_path_for_remote_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=root / "storage" / "generated",
                body={
                    "action": "file_info",
                    "provider": "google_drive",
                    "connection_id": "drive_conn_123",
                    "drive_file_id": "drive_file_123",
                    "workspace_relative_path": "storage/generated/report.md",
                },
            )

            self.assertEqual(result["status_code"], 400)
            self.assertEqual(result["json"]["error"], "validation_error")
            self.assertIn("workspace_relative_path", result["json"]["detail"])

    def test_backend_renames_file_inside_same_storage_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            generated_root.mkdir(parents=True)
            (generated_root / "report.md").write_text("# report", encoding="utf-8")

            renamed = self.run_backend(
                data_root=root / "data" / "storage",
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
                data_root=root / "data" / "storage",
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

    def test_backend_file_id_survives_rename_and_reference_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            generated_root.mkdir(parents=True)
            (generated_root / "report.md").write_text("# report", encoding="utf-8")

            catalog = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "catalog"},
            )
            file_id = catalog["json"]["files"][0]["id"]
            renamed = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={
                    "action": "rename_file",
                    "role": "generated",
                    "relative_path": "report.md",
                    "new_name": "final-report.md",
                },
            )
            resolved = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "references.resolve", "entity_id": file_id},
            )

            self.assertTrue(file_id.startswith("file_"))
            self.assertEqual(renamed["json"]["file"]["id"], file_id)
            self.assertTrue(resolved["json"]["exists"])
            self.assertEqual(resolved["json"]["entity_id"], file_id)
            self.assertEqual(resolved["json"]["workspace_relative_path"], "storage/generated/final-report.md")

    def test_backend_updates_markdown_file_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            generated_root.mkdir(parents=True)
            target = generated_root / "report.md"
            target.write_text("# report\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n", encoding="utf-8")
            (generated_root / "notes.txt").write_text("plain text", encoding="utf-8")

            updated = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={
                    "action": "update_markdown_file",
                    "workspace_relative_path": "storage/generated/report.md",
                    "content": "# updated\n\n| Name | Value |\n| --- | ---: |\n| Speed | 10 |\n",
                },
            )
            rejected = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={
                    "action": "update_markdown_file",
                    "workspace_relative_path": "storage/generated/notes.txt",
                    "content": "# invalid",
                },
            )

            self.assertEqual(updated["status_code"], 200)
            self.assertEqual(updated["json"]["file"]["preview_kind"], "markdown")
            self.assertEqual(target.read_text(encoding="utf-8"), "# updated\n\n| Name | Value |\n| --- | ---: |\n| Speed | 10 |\n")
            self.assertEqual(rejected["status_code"], 400)
            self.assertEqual((generated_root / "notes.txt").read_text(encoding="utf-8"), "plain text")

    def test_backend_writes_file_content_through_generic_interface(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            generated_root.mkdir(parents=True)
            target = generated_root / "reports" / "summary.txt"

            created = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={
                    "action": "file.content.write",
                    "role": "generated",
                    "relative_path": "reports/summary.txt",
                    "mode": "create",
                    "content": "first version",
                },
            )
            overwritten = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={
                    "action": "write_file",
                    "workspace_relative_path": "storage/generated/reports/summary.txt",
                    "mode": "overwrite",
                    "confirm": True,
                    "content_base64": "c2Vjb25kIHZlcnNpb24=",
                },
            )
            implicit_overwrite = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={
                    "action": "file.content.write",
                    "workspace_relative_path": "storage/generated/reports/summary.txt",
                    "content": "third version",
                },
            )
            unconfirmed_overwrite = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={
                    "action": "file.content.write",
                    "workspace_relative_path": "storage/generated/reports/summary.txt",
                    "mode": "overwrite",
                    "content": "third version",
                },
            )
            rejected = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={
                    "action": "file.content.write",
                    "role": "generated",
                    "relative_path": "../escape.txt",
                    "mode": "upsert",
                    "content": "nope",
                },
            )

            self.assertEqual(created["status_code"], 200)
            self.assertEqual(created["json"]["file"]["workspace_relative_path"], "storage/generated/reports/summary.txt")
            self.assertEqual(created["json"]["bytes_written"], len("first version"))
            self.assertEqual(overwritten["status_code"], 200)
            self.assertEqual(target.read_text(encoding="utf-8"), "second version")
            self.assertEqual(implicit_overwrite["status_code"], 400)
            self.assertEqual(unconfirmed_overwrite["status_code"], 400)
            self.assertIn("confirm=true", unconfirmed_overwrite["json"]["detail"])
            self.assertEqual(rejected["status_code"], 400)

    def test_backend_write_versioned_upload_overwrite_and_read_handle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            uploaded_root = root / "storage" / "uploaded"
            generated_root.mkdir(parents=True)
            uploaded_root.mkdir(parents=True)
            data_root = root / "data" / "storage"
            target = generated_root / "reports" / "summary.txt"

            created = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "file.content.write",
                    "workspace_relative_path": "storage/generated/reports/summary.txt",
                    "mode": "create",
                    "content": "first",
                },
            )
            versioned = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "file.content.write",
                    "workspace_relative_path": "storage/generated/reports/summary.txt",
                    "mode": "versioned",
                    "content": "second",
                },
            )
            uploaded = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "upload_file",
                    "role": "generated",
                    "folder_relative_path": "reports",
                    "file_name": "summary.txt",
                    "mode": "overwrite",
                    "confirm": True,
                    "content_base64": b64encode(b"third").decode("ascii"),
                },
            )
            handle = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "file.content.read",
                    "workspace_relative_path": "storage/generated/reports/summary.txt",
                    "return_handle": True,
                    "include_local_path": True,
                },
            )

            self.assertEqual(created["status_code"], 200, created)
            self.assertEqual(versioned["status_code"], 200, versioned)
            self.assertEqual(versioned["json"]["audit"]["effective_mode"], "versioned")
            self.assertEqual(versioned["json"]["audit"]["requested_workspace_relative_path"], "storage/generated/reports/summary.txt")
            self.assertEqual(versioned["json"]["audit"]["workspace_relative_path"], "storage/generated/reports/summary.v2.txt")
            self.assertTrue(versioned["json"]["audit"]["previous_sha256"])
            self.assertFalse(versioned["json"]["audit"]["replaced"])
            self.assertEqual(uploaded["status_code"], 200, uploaded)
            self.assertEqual(target.read_text(encoding="utf-8"), "third")
            self.assertEqual((generated_root / "reports" / "summary.v2.txt").read_text(encoding="utf-8"), "second")
            self.assertTrue(uploaded["json"]["audit"]["previous_sha256"])
            self.assertTrue(uploaded["json"]["audit"]["replaced"])
            self.assertEqual(handle["status_code"], 200, handle)
            self.assertNotIn("content_base64", handle["json"])
            self.assertEqual(handle["json"]["file_handle"]["workspace_relative_path"], "storage/generated/reports/summary.txt")
            self.assertNotIn("local_path", handle["json"]["file_handle"])

    def test_backend_rejects_writes_over_configured_storage_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            generated_root.mkdir(parents=True)

            with patch.dict(os.environ, {"MAVERICK_STORAGE_MAX_BYTES": "4"}):
                rejected = self.run_backend(
                    data_root=root / "data" / "storage",
                    uploaded_root=root / "storage" / "uploaded",
                    generated_root=generated_root,
                    body={
                        "action": "file.content.write",
                        "role": "generated",
                        "relative_path": "too-large.txt",
                        "mode": "create",
                        "content": "hello",
                    },
                )

            self.assertEqual(rejected["status_code"], 400)
            self.assertEqual(rejected["json"]["error"], "validation_error")
            self.assertFalse((generated_root / "too-large.txt").exists())

    def test_backend_creates_folder_and_moves_file_inside_storage_role(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            uploaded_root = root / "storage" / "uploaded"
            generated_root.mkdir(parents=True)
            uploaded_root.mkdir(parents=True)
            source = generated_root / "report.md"
            source.write_text("# report", encoding="utf-8")

            created = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "create_folder", "role": "generated", "folder_name": "Reports"},
            )
            moved = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "move_file",
                    "role": "generated",
                    "relative_path": "report.md",
                    "target_folder_relative_path": "Reports",
                },
            )
            self.assertEqual(moved["status_code"], 200)
            self.assertEqual(moved["json"]["file"]["workspace_relative_path"], "storage/generated/Reports/report.md")
            self.assertTrue((generated_root / "Reports" / "report.md").is_file())

            moved_out = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "move_file",
                    "workspace_relative_path": "storage/generated/Reports/report.md",
                    "target_folder_relative_path": "",
                },
            )
            rejected = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "create_folder",
                    "role": "generated",
                    "parent_relative_path": "../escape",
                    "folder_name": "Bad",
                },
            )

            self.assertEqual(created["status_code"], 200)
            self.assertEqual(created["json"]["folder"]["workspace_relative_path"], "storage/generated/Reports")
            self.assertEqual(moved_out["status_code"], 200)
            self.assertEqual(moved_out["json"]["file"]["workspace_relative_path"], "storage/generated/report.md")
            self.assertTrue((generated_root / "report.md").is_file())
            self.assertEqual(rejected["status_code"], 400)

    def test_backend_move_file_preserves_id_and_rejects_invalid_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            uploaded_root = root / "storage" / "uploaded"
            generated_root.mkdir(parents=True)
            uploaded_root.mkdir(parents=True)
            data_root = root / "data" / "storage"

            created_file = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "upload_file",
                    "role": "generated",
                    "file_name": "report.md",
                    "content_base64": b64encode(b"# report").decode("ascii"),
                },
            )
            created = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "create_folder", "role": "generated", "folder_name": "Reports"},
            )
            moved = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "move_file",
                    "role": "generated",
                    "relative_path": "report.md",
                    "target_folder_relative_path": "Reports",
                },
            )
            collision_source = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "upload_file",
                    "role": "generated",
                    "file_name": "report.md",
                    "content_base64": b64encode(b"# duplicate").decode("ascii"),
                },
            )
            collision = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "move_file",
                    "role": "generated",
                    "relative_path": "report.md",
                    "target_folder_relative_path": "Reports",
                },
            )
            invalid_role = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "move_file",
                    "role": "all",
                    "relative_path": "report.md",
                    "target_folder_relative_path": "Reports",
                },
            )
            invalid_path = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "move_file",
                    "role": "generated",
                    "relative_path": "../report.md",
                    "target_folder_relative_path": "Reports",
                },
            )

            self.assertEqual(created_file["status_code"], 200)
            self.assertEqual(created["status_code"], 200)
            self.assertEqual(moved["status_code"], 200)
            self.assertEqual(moved["json"]["file"]["id"], created_file["json"]["file"]["id"])
            self.assertEqual(moved["json"]["file"]["workspace_relative_path"], "storage/generated/Reports/report.md")
            self.assertEqual(collision_source["status_code"], 200)
            self.assertEqual(collision["status_code"], 400)
            self.assertEqual(collision["json"]["error"], "validation_error")
            self.assertTrue((generated_root / "report.md").is_file())
            self.assertTrue((generated_root / "Reports" / "report.md").is_file())
            self.assertEqual(invalid_role["status_code"], 400)
            self.assertEqual(invalid_path["status_code"], 400)

    def test_backend_moves_folder_tree_inside_storage_role(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            uploaded_root = root / "storage" / "uploaded"
            data_root = root / "data" / "storage"
            report_folder = generated_root / "Reports"
            nested_folder = report_folder / "Q1"
            nested_folder.mkdir(parents=True)
            uploaded_root.mkdir(parents=True)
            (report_folder / "summary.md").write_text("# summary", encoding="utf-8")
            (nested_folder / "data.txt").write_text("data", encoding="utf-8")

            original_catalog = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "catalog", "role": "generated", "folder_path": "Reports", "sync": True},
            )
            created_archive = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "create_folder", "role": "generated", "folder_name": "Archive"},
            )
            moved = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "move_folder",
                    "role": "generated",
                    "relative_path": "Reports",
                    "target_folder_relative_path": "Archive",
                },
            )
            moved_catalog = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "catalog", "role": "generated", "folder_path": "Archive/Reports"},
            )

            self.assertEqual(original_catalog["status_code"], 200)
            self.assertEqual(created_archive["status_code"], 200)
            self.assertEqual(moved["status_code"], 200)
            self.assertEqual(moved["json"]["folder"]["workspace_relative_path"], "storage/generated/Archive/Reports")
            self.assertFalse(report_folder.exists())
            self.assertTrue((generated_root / "Archive" / "Reports" / "summary.md").is_file())
            self.assertTrue((generated_root / "Archive" / "Reports" / "Q1" / "data.txt").is_file())
            original_summary = next(item for item in original_catalog["json"]["files"] if item["relative_path"] == "Reports/summary.md")
            moved_summary = next(item for item in moved_catalog["json"]["files"] if item["relative_path"] == "Archive/Reports/summary.md")
            self.assertEqual(moved_summary["id"], original_summary["id"])
            folder_paths = {item["workspace_relative_path"] for item in moved_catalog["json"]["folders"]}
            self.assertIn("storage/generated/Archive/Reports", folder_paths)
            self.assertIn("storage/generated/Archive/Reports/Q1", folder_paths)
            self.assertNotIn("storage/generated/Reports", folder_paths)

            rejected_child = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "move_folder",
                    "role": "generated",
                    "relative_path": "Archive/Reports",
                    "target_folder_relative_path": "Archive/Reports/Q1",
                },
            )
            recreated_reports = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "create_folder", "role": "generated", "folder_name": "Reports"},
            )
            rejected_collision = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "move_folder",
                    "role": "generated",
                    "relative_path": "Reports",
                    "target_folder_relative_path": "Archive",
                },
            )
            rejected_root = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "move_folder",
                    "role": "generated",
                    "relative_path": "",
                    "target_folder_relative_path": "Archive",
                },
            )
            rejected_escape = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "move_folder",
                    "role": "generated",
                    "relative_path": "../Reports",
                    "target_folder_relative_path": "Archive",
                },
            )

            self.assertEqual(rejected_child["status_code"], 400)
            self.assertEqual(recreated_reports["status_code"], 200)
            self.assertEqual(rejected_collision["status_code"], 400)
            self.assertEqual(rejected_root["status_code"], 400)
            self.assertEqual(rejected_escape["status_code"], 400)

    def test_backend_batch_moves_files_and_folders_under_one_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            uploaded_root = root / "storage" / "uploaded"
            data_root = root / "data" / "storage"
            report_folder = generated_root / "Reports"
            nested_folder = report_folder / "Q1"
            archive_folder = generated_root / "Archive"
            nested_folder.mkdir(parents=True)
            archive_folder.mkdir(parents=True)
            uploaded_root.mkdir(parents=True)
            (generated_root / "loose.md").write_text("# loose", encoding="utf-8")
            (report_folder / "summary.md").write_text("# summary", encoding="utf-8")
            (nested_folder / "data.txt").write_text("data", encoding="utf-8")

            original_catalog = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "catalog", "role": "generated", "sync": True},
            )
            moved = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "move_items",
                    "role": "generated",
                    "target_folder_relative_path": "Archive",
                    "files": [
                        {"role": "generated", "relative_path": "loose.md"},
                        {"role": "generated", "relative_path": "Reports/Q1/data.txt"},
                    ],
                    "folders": [{"role": "generated", "relative_path": "Reports"}],
                },
            )
            moved_catalog = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "catalog", "role": "generated", "folder_path": "Archive", "sync": True},
            )

            self.assertEqual(original_catalog["status_code"], 200)
            self.assertEqual(moved["status_code"], 200)
            self.assertEqual(
                [item["file"]["workspace_relative_path"] for item in moved["json"]["files"]],
                ["storage/generated/Archive/loose.md"],
            )
            self.assertEqual(
                [item["folder"]["workspace_relative_path"] for item in moved["json"]["folders"]],
                ["storage/generated/Archive/Reports"],
            )
            self.assertFalse((generated_root / "loose.md").exists())
            self.assertFalse(report_folder.exists())
            self.assertTrue((generated_root / "Archive" / "loose.md").is_file())
            self.assertTrue((generated_root / "Archive" / "Reports" / "summary.md").is_file())
            self.assertTrue((generated_root / "Archive" / "Reports" / "Q1" / "data.txt").is_file())
            original_loose = next(item for item in original_catalog["json"]["files"] if item["relative_path"] == "loose.md")
            moved_loose = next(item for item in moved_catalog["json"]["files"] if item["relative_path"] == "Archive/loose.md")
            self.assertEqual(moved_loose["id"], original_loose["id"])
            self.assertEqual(moved["json"]["files"][0]["previous"]["relative_path"], "loose.md")
            self.assertEqual(moved["json"]["folders"][0]["previous"]["relative_path"], "Reports")

            (generated_root / "again.md").write_text("# again", encoding="utf-8")
            (generated_root / "Archive" / "again.md").write_text("# collision", encoding="utf-8")
            rejected_collision = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "move_items",
                    "role": "generated",
                    "target_folder_relative_path": "Archive",
                    "files": [{"role": "generated", "relative_path": "again.md"}],
                    "folders": [],
                },
            )
            self.assertEqual(rejected_collision["status_code"], 400)
            self.assertTrue((generated_root / "again.md").is_file())

            (generated_root / "second.md").write_text("# second", encoding="utf-8")
            rejected_partial_move = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "move_items",
                    "role": "generated",
                    "target_folder_relative_path": "Archive",
                    "files": [
                        {"role": "generated", "relative_path": "second.md"},
                        {"role": "generated", "relative_path": "again.md"},
                    ],
                    "folders": [],
                },
            )
            self.assertEqual(rejected_partial_move["status_code"], 400)
            self.assertTrue((generated_root / "second.md").is_file())
            self.assertFalse((generated_root / "Archive" / "second.md").exists())

    def test_backend_uploads_file_into_existing_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            uploaded_root = root / "storage" / "uploaded"
            target_folder = uploaded_root / "Receipts"
            target_folder.mkdir(parents=True)
            generated_root.mkdir(parents=True)

            uploaded = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "upload_file",
                    "role": "uploaded",
                    "folder_relative_path": "Receipts",
                    "file_name": "invoice.txt",
                    "content_base64": "aGVsbG8=",
                },
            )
            duplicate = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "upload_file",
                    "role": "uploaded",
                    "folder_relative_path": "Receipts",
                    "file_name": "invoice.txt",
                    "content_base64": "aGVsbG8=",
                },
            )
            empty = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "upload_file",
                    "role": "uploaded",
                    "folder_relative_path": "Receipts",
                    "file_name": "empty.txt",
                    "content_base64": "",
                },
            )
            escaped = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "upload_file",
                    "role": "uploaded",
                    "folder_relative_path": "Receipts",
                    "file_name": "../invoice.txt",
                    "content_base64": "aGVsbG8=",
                },
            )

            self.assertEqual(uploaded["status_code"], 200)
            self.assertEqual(uploaded["json"]["file"]["workspace_relative_path"], "storage/uploaded/Receipts/invoice.txt")
            self.assertEqual(uploaded["json"]["bytes_written"], 5)
            self.assertEqual((target_folder / "invoice.txt").read_text(encoding="utf-8"), "hello")
            self.assertEqual(duplicate["status_code"], 400)
            self.assertEqual(empty["status_code"], 200)
            self.assertEqual(empty["json"]["bytes_written"], 0)
            self.assertEqual((target_folder / "empty.txt").read_bytes(), b"")
            self.assertEqual(escaped["status_code"], 400)

    def test_backend_local_upload_session_writes_file_from_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            uploaded_root = root / "storage" / "uploaded"
            generated_root.mkdir(parents=True)
            uploaded_root.mkdir(parents=True)
            data_root = root / "data" / "storage"
            first = b"hello "
            second = b"world"

            started = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "local_upload_session.start",
                    "role": "generated",
                    "file_name": "large.txt",
                    "content_type": "text/plain",
                    "size_bytes": len(first) + len(second),
                },
            )
            session_id = started["json"]["upload_session"]["id"]
            first_chunk = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "local_upload_session.chunk",
                    "local_upload_session_id": session_id,
                    "chunk_offset": 0,
                    "content_base64": b64encode(first).decode("ascii"),
                },
            )
            completed = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "local_upload_session.chunk",
                    "local_upload_session_id": session_id,
                    "chunk_offset": len(first),
                    "content_base64": b64encode(second).decode("ascii"),
                },
            )
            catalog = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "catalog", "sync": True},
            )

            self.assertEqual(started["status_code"], 200)
            self.assertEqual(first_chunk["json"]["expected_offset"], len(first))
            self.assertEqual(first_chunk["app_events"], [])
            self.assertEqual(completed["status_code"], 200)
            self.assertEqual(completed["json"]["status"], "uploaded")
            self.assertEqual(completed["app_events"], [{"type": "maverick.app.data-changed", "resource": "files"}])
            self.assertEqual(completed["json"]["file"]["workspace_relative_path"], "storage/generated/large.txt")
            self.assertEqual((generated_root / "large.txt").read_bytes(), first + second)
            self.assertEqual(catalog["json"]["files"][0]["file_id"], completed["json"]["file"]["file_id"])

    def test_cli_upload_local_file_writes_binary_without_inline_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            uploaded_root = root / "storage" / "uploaded"
            generated_root.mkdir(parents=True)
            uploaded_root.mkdir(parents=True)
            data_root = root / "data" / "storage"
            source = root / "tmp" / "output.pdf"
            source.parent.mkdir(parents=True)
            payload = b"%PDF-1.4\n% local upload\n"
            source.write_bytes(payload)

            result = self.run_cli(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                arguments={
                    "action": "upload_local_file",
                    "source_path": str(source),
                    "workspace_relative_path": "storage/generated/pdf-edits/output.pdf",
                    "content_type": "application/pdf",
                    "mode": "create",
                },
            )
            duplicate = self.run_cli(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                arguments={
                    "action": "upload_local_file",
                    "source_path": str(source),
                    "workspace_relative_path": "storage/generated/pdf-edits/output.pdf",
                    "content_type": "application/pdf",
                    "mode": "create",
                },
            )

            self.assertEqual(result["status_code"], 200)
            self.assertEqual(result["status"], "uploaded")
            self.assertEqual(result["bytes_uploaded"], len(payload))
            self.assertEqual(result["file"]["workspace_relative_path"], "storage/generated/pdf-edits/output.pdf")
            self.assertEqual((generated_root / "pdf-edits" / "output.pdf").read_bytes(), payload)
            self.assertEqual(result["app_events"], [{"type": "maverick.app.data-changed", "resource": "files"}])
            self.assertEqual(duplicate["status_code"], 400)

    def test_cli_upload_local_file_rejects_sandbox_source_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace_root = root / "workspace"
            generated_root = workspace_root / "storage" / "generated"
            uploaded_root = workspace_root / "storage" / "uploaded"
            generated_root.mkdir(parents=True)
            uploaded_root.mkdir(parents=True)
            data_root = workspace_root / "data" / "storage"
            source = root / "outside.pdf"
            source.write_bytes(b"%PDF-1.4\n% outside workspace\n")

            result = self.run_cli(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                workspace_root=workspace_root,
                arguments={
                    "action": "upload_local_file",
                    "source_path": str(source),
                    "workspace_relative_path": "storage/generated/pdf-edits/outside.pdf",
                    "content_type": "application/pdf",
                    "mode": "create",
                },
            )

            self.assertEqual(result["status_code"], 400)
            self.assertEqual(result["error"], "validation_error")
            self.assertIn("inside the workspace root", result["detail"])
            self.assertFalse((generated_root / "pdf-edits" / "outside.pdf").exists())

    def test_cli_upload_local_file_allows_operator_source_in_full_access_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace_root = root / "workspace"
            generated_root = workspace_root / "storage" / "generated"
            uploaded_root = workspace_root / "storage" / "uploaded"
            generated_root.mkdir(parents=True)
            uploaded_root.mkdir(parents=True)
            data_root = workspace_root / "data" / "storage"
            source = root / "outside.pdf"
            payload = b"%PDF-1.4\n% operator local upload\n"
            source.write_bytes(payload)

            result = self.run_cli(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                workspace_root=workspace_root,
                effective_mode="full-access",
                arguments={
                    "action": "upload_local_file",
                    "source_path": str(source),
                    "workspace_relative_path": "storage/generated/pdf-edits/operator.pdf",
                    "content_type": "application/pdf",
                    "mode": "create",
                },
            )

            self.assertEqual(result["status_code"], 200)
            self.assertEqual(result["status"], "uploaded")
            self.assertEqual((generated_root / "pdf-edits" / "operator.pdf").read_bytes(), payload)

    def test_backend_local_upload_session_reserves_storage_quota(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            uploaded_root = root / "storage" / "uploaded"
            generated_root.mkdir(parents=True)
            uploaded_root.mkdir(parents=True)
            data_root = root / "data" / "storage"
            with patch.dict(os.environ, {"MAVERICK_STORAGE_MAX_BYTES": "10"}, clear=False):
                first = self.run_backend(
                    data_root=data_root,
                    uploaded_root=uploaded_root,
                    generated_root=generated_root,
                    body={
                        "action": "local_upload_session.start",
                        "role": "generated",
                        "file_name": "reserved.bin",
                        "size_bytes": 10,
                    },
                )
                second = self.run_backend(
                    data_root=data_root,
                    uploaded_root=uploaded_root,
                    generated_root=generated_root,
                    body={
                        "action": "local_upload_session.start",
                        "role": "generated",
                        "file_name": "other.bin",
                        "size_bytes": 1,
                    },
                )
                canceled = self.run_backend(
                    data_root=data_root,
                    uploaded_root=uploaded_root,
                    generated_root=generated_root,
                    body={
                        "action": "local_upload_session.cancel",
                        "local_upload_session_id": first["json"]["upload_session"]["id"],
                    },
                )
                after_cancel = self.run_backend(
                    data_root=data_root,
                    uploaded_root=uploaded_root,
                    generated_root=generated_root,
                    body={
                        "action": "local_upload_session.start",
                        "role": "generated",
                        "file_name": "other.bin",
                        "size_bytes": 10,
                    },
                )

            self.assertEqual(first["status_code"], 200)
            self.assertEqual(second["status_code"], 400)
            self.assertEqual(second["json"]["detail"], "workspace_storage_quota_exceeded")
            self.assertEqual(canceled["status_code"], 200)
            self.assertEqual(after_cancel["status_code"], 200)

    def test_backend_local_upload_session_rejects_forward_offset_and_declared_oversize(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            uploaded_root = root / "storage" / "uploaded"
            generated_root.mkdir(parents=True)
            uploaded_root.mkdir(parents=True)
            data_root = root / "data" / "storage"

            oversized = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "local_upload_session.start",
                    "role": "generated",
                    "file_name": "too-large.bin",
                    "size_bytes": 500 * 1024 * 1024 + 1,
                },
            )
            started = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "local_upload_session.start",
                    "role": "generated",
                    "file_name": "clip.bin",
                    "size_bytes": 5,
                },
            )
            session_id = started["json"]["upload_session"]["id"]
            ahead = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={
                    "action": "local_upload_session.chunk",
                    "local_upload_session_id": session_id,
                    "chunk_offset": 2,
                    "content_base64": b64encode(b"abc").decode("ascii"),
                },
            )
            canceled = self.run_backend(
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
                body={"action": "local_upload_session.cancel", "local_upload_session_id": session_id},
            )

            self.assertEqual(oversized["status_code"], 400)
            self.assertIn(str(500 * 1024 * 1024), oversized["json"]["detail"])
            self.assertEqual(ahead["status_code"], 400)
            self.assertEqual(canceled["status_code"], 200)
            self.assertFalse((data_root / "run" / "local_upload_sessions" / f"{session_id}.part").exists())

    def test_backend_deletes_file_inside_workspace_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            generated_root.mkdir(parents=True)
            target = generated_root / "report.md"
            target.write_text("# report", encoding="utf-8")

            deleted = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "delete_file", "workspace_relative_path": "storage/generated/report.md"},
            )
            rejected = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "delete_file", "role": "generated", "relative_path": "../secret.txt"},
            )

            self.assertEqual(deleted["status_code"], 200)
            self.assertTrue(deleted["json"]["deleted"])
            self.assertEqual(deleted["json"]["file"]["workspace_relative_path"], "storage/generated/report.md")
            self.assertFalse(target.exists())
            self.assertEqual(rejected["status_code"], 400)

    def test_backend_downloads_and_deletes_folder_inside_workspace_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            report_folder = generated_root / "Reports"
            nested_folder = report_folder / "Q1"
            nested_folder.mkdir(parents=True)
            (report_folder / "summary.md").write_text("# summary", encoding="utf-8")
            (nested_folder / "data.txt").write_text("data", encoding="utf-8")

            archive = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "download_folder", "role": "generated", "relative_path": "Reports"},
            )
            deleted = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "delete_folder", "role": "generated", "relative_path": "Reports"},
            )
            rejected_root = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "delete_folder", "role": "generated", "relative_path": ""},
            )
            rejected_escape = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "delete_folder", "role": "generated", "relative_path": "../secret"},
            )

            self.assertEqual(archive["status_code"], 200)
            self.assertEqual(archive["json"]["folder"]["workspace_relative_path"], "storage/generated/Reports")
            self.assertEqual(archive["json"]["file_name"], "Reports.zip")
            with zipfile.ZipFile(BytesIO(b64decode(archive["json"]["content_base64"]))) as zip_file:
                self.assertEqual(set(zip_file.namelist()), {"summary.md", "Q1/data.txt"})
            self.assertEqual(deleted["status_code"], 200)
            self.assertTrue(deleted["json"]["deleted"])
            self.assertFalse(report_folder.exists())
            self.assertEqual(rejected_root["status_code"], 400)
            self.assertEqual(rejected_escape["status_code"], 400)

    def test_backend_media_route_downloads_folder_as_file_response(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            report_folder = generated_root / "Reports"
            report_folder.mkdir(parents=True)
            (report_folder / "summary.md").write_text("# summary", encoding="utf-8")
            data_root = root / "data" / "storage"

            response = run_json_entrypoint(
                STORAGE_ROOT / "backend" / "app_backend.py",
                payload={
                    "data_root": str(data_root),
                    "uploaded_storage_root": str(root / "storage" / "uploaded"),
                    "generated_storage_root": str(generated_root),
                    "route_path": "/api/apps/storage/media",
                    "method": "GET",
                    "query": {
                        "media_kind": "folder",
                        "role": "generated",
                        "relative_path": "Reports",
                        "download": "1",
                    },
                },
                cwd=STORAGE_ROOT,
            )

            self.assertEqual(response["status_code"], 200)
            self.assertEqual(response["json"]["folder"]["workspace_relative_path"], "storage/generated/Reports")
            self.assertEqual(response["file_response"]["file_name"], "Reports.zip")
            self.assertTrue(response["file_response"]["delete_after_send"])
            archive_path = Path(response["file_response"]["path"])
            self.assertTrue(archive_path.is_file())
            with zipfile.ZipFile(archive_path) as zip_file:
                self.assertEqual(zip_file.namelist(), ["summary.md"])

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
            odt = generated_root / "instructions.odt"
            with zipfile.ZipFile(odt, "w") as archive:
                archive.writestr(
                    "content.xml",
                    """<?xml version="1.0" encoding="UTF-8"?>
                    <office:document-content
                      xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
                      xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
                      <office:body><office:text><text:p>ODT operative instructions</text:p></office:text></office:body>
                    </office:document-content>""",
                )

            preview = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "preview_text", "workspace_relative_path": "storage/generated/brief.docx"},
            )
            cached_preview = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "preview_text", "workspace_relative_path": "storage/generated/brief.docx"},
            )
            odt_text = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "read_text", "workspace_relative_path": "storage/generated/instructions.odt"},
            )

            self.assertEqual(preview["status_code"], 200)
            self.assertEqual(preview["json"]["file"]["preview_kind"], "document")
            self.assertIn("Quarterly brief", preview["json"]["preview_text"])
            self.assertFalse(preview["json"]["cache_hit"])
            self.assertTrue(cached_preview["json"]["cache_hit"])
            self.assertEqual(odt_text["status_code"], 200, odt_text)
            self.assertIn("ODT operative instructions", odt_text["json"]["text"])

    def test_backend_extracts_table_preview_for_csv_and_xlsx(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            generated_root.mkdir(parents=True)
            csv_file = generated_root / "leads.csv"
            csv_file.write_text('Name,Company,Notes\nAlice,Acme,"met at event"\nBob,,Follow up\n', encoding="utf-8")
            xlsx = generated_root / "forecast.xlsx"
            with zipfile.ZipFile(xlsx, "w") as archive:
                archive.writestr(
                    "xl/sharedStrings.xml",
                    """<?xml version="1.0" encoding="UTF-8"?>
                    <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                      <si><t>Month</t></si><si><t>Revenue</t></si><si><t>April</t></si>
                    </sst>""",
                )
                archive.writestr(
                    "xl/worksheets/sheet1.xml",
                    """<?xml version="1.0" encoding="UTF-8"?>
                    <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                      <sheetData>
                        <row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="s"><v>1</v></c></row>
                        <row r="2"><c r="A2" t="s"><v>2</v></c><c r="C2"><v>1200</v></c></row>
                      </sheetData>
                    </worksheet>""",
                )

            csv_preview = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "preview_table", "workspace_relative_path": "storage/generated/leads.csv", "max_rows": 20, "max_columns": 10},
            )
            xlsx_preview = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "preview_table", "workspace_relative_path": "storage/generated/forecast.xlsx", "max_rows": 20, "max_columns": 10},
            )

            self.assertEqual(csv_preview["status_code"], 200)
            self.assertEqual(csv_preview["json"]["sheets"][0]["rows"][1], ["Alice", "Acme", "met at event"])
            self.assertEqual(csv_preview["json"]["sheets"][0]["rows"][2], ["Bob", "", "Follow up"])
            self.assertEqual(xlsx_preview["status_code"], 200)
            self.assertEqual(xlsx_preview["json"]["file"]["preview_kind"], "spreadsheet")
            self.assertEqual(xlsx_preview["json"]["sheets"][0]["rows"][0], ["Month", "", "Revenue"])
            self.assertEqual(xlsx_preview["json"]["sheets"][0]["rows"][1], ["April", "", "1200"])

    def test_backend_text_preview_is_bounded_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            generated_root.mkdir(parents=True)
            body = "\n".join(f"Line {index:04d} " + ("content " * 8) for index in range(260))
            markdown = generated_root / "long.md"
            markdown_content = f"# Long report\n\n{body}\n\nFINAL-MARKER"
            markdown.write_text(markdown_content, encoding="utf-8")

            full_preview = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "preview_text", "workspace_relative_path": "storage/generated/long.md"},
            )
            text_read = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "file.text.read", "workspace_relative_path": "storage/generated/long.md"},
            )
            text_window = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "read_text", "workspace_relative_path": "storage/generated/long.md", "offset": 2, "max_chars": 8},
            )
            limited_preview = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "preview_text", "workspace_relative_path": "storage/generated/long.md", "max_chars": 1200},
            )

            self.assertEqual(full_preview["status_code"], 200)
            self.assertNotIn("FINAL-MARKER", full_preview["json"]["preview_text"])
            self.assertTrue(full_preview["json"]["preview_text"].endswith("…"))
            self.assertEqual(text_read["status_code"], 200)
            self.assertIn("FINAL-MARKER", text_read["json"]["text"])
            self.assertEqual(text_read["json"]["text_char_count"], len(markdown_content))
            self.assertTrue(text_read["json"]["complete"])
            self.assertFalse(text_read["json"]["has_more"])
            self.assertEqual(text_window["status_code"], 200)
            self.assertEqual(text_window["json"]["text"], markdown_content[2:10])
            self.assertEqual(text_window["json"]["next_offset"], 10)
            self.assertFalse(text_window["json"]["complete"])
            self.assertEqual(limited_preview["status_code"], 200)
            self.assertNotIn("FINAL-MARKER", limited_preview["json"]["preview_text"])
            self.assertTrue(limited_preview["json"]["preview_text"].endswith("…"))

    def test_backend_table_preview_is_bounded_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            generated_root.mkdir(parents=True)
            csv_file = generated_root / "wide.csv"
            header = [f"col_{index:02d}" for index in range(55)]
            rows = [
                [f"r{row_index:03d}c{column_index:02d}" for column_index in range(55)]
                for row_index in range(240)
            ]
            csv_file.write_text(
                "\n".join(",".join(row) for row in [header, *rows]) + "\n",
                encoding="utf-8",
            )

            full_preview = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "preview_table", "workspace_relative_path": "storage/generated/wide.csv"},
            )
            limited_preview = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "preview_table", "workspace_relative_path": "storage/generated/wide.csv", "max_rows": 10, "max_columns": 5},
            )

            self.assertEqual(full_preview["status_code"], 200)
            full_sheet = full_preview["json"]["sheets"][0]
            self.assertEqual(len(full_sheet["rows"]), 200)
            self.assertEqual(len(full_sheet["rows"][0]), 50)
            self.assertTrue(full_sheet["truncated_rows"])
            self.assertTrue(full_sheet["truncated_columns"])

            self.assertEqual(limited_preview["status_code"], 200)
            limited_sheet = limited_preview["json"]["sheets"][0]
            self.assertEqual(len(limited_sheet["rows"]), 10)
            self.assertEqual(len(limited_sheet["rows"][0]), 5)
            self.assertTrue(limited_sheet["truncated_rows"])
            self.assertTrue(limited_sheet["truncated_columns"])

    def test_backend_catalog_supports_pagination_and_rejects_invalid_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            generated_root.mkdir(parents=True)
            for index in range(3):
                (generated_root / f"file-{index}.txt").write_text(str(index), encoding="utf-8")

            page = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "catalog", "limit": 2, "offset": 1, "sort_by": "relative_path", "sort_direction": "asc"},
            )
            rejected_catalog = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "catalog", "limit": "many"},
            )
            rejected_preview = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "preview_table", "workspace_relative_path": "storage/generated/file-0.txt", "max_rows": "many"},
            )

            self.assertEqual(page["status_code"], 200)
            self.assertEqual(page["json"]["pagination"]["total"], 3)
            self.assertEqual([item["relative_path"] for item in page["json"]["files"]], ["file-1.txt", "file-2.txt"])
            self.assertTrue(page["json"]["pagination"]["has_more"] is False)
            self.assertEqual(rejected_catalog["status_code"], 400)
            self.assertEqual(rejected_preview["status_code"], 400)

    def test_backend_unknown_action_returns_guided_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            rejected = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=root / "storage" / "generated",
                body={"action": "not_real"},
            )

            self.assertEqual(rejected["status_code"], 400)
            payload = rejected["json"]
            self.assertEqual(payload["error"], "validation_error")
            self.assertIn("action", payload["allowed_values"])
            self.assertIn("operations.manifest", payload["allowed_values"]["action"])
            self.assertIn("file.catalog.list", payload["allowed_values"]["action"])
            self.assertIn("file.preview.text", payload["allowed_values"]["action"])
            self.assertIn("file.preview.table", payload["allowed_values"]["action"])
            self.assertEqual(payload["example"]["action"], "operations.manifest")

    def test_cli_schema_restricts_file_roles_and_allows_root_folder_reads(self) -> None:
        schema = self.storage_cli_argument_schema()

        valid_payloads = [
            {"action": "catalog", "role": "all"},
            {"action": "file_info", "role": "generated", "relative_path": "report.md"},
            {"action": "read_file", "role": "uploaded", "relative_path": "source.txt"},
            {"action": "read_text", "role": "generated", "relative_path": "report.md"},
            {"action": "upload_local_file", "source_path": "/workspace/output.pdf", "workspace_relative_path": "storage/generated/pdf-edits/output.pdf", "mode": "create"},
            {"action": "image.inspect", "workspace_relative_path": "storage/generated/id-front.png"},
            {"action": "image.compose_pair", "images": ["storage/generated/id-front.png", "storage/generated/id-back.png"], "file_name": "id-card.jpg"},
            {"action": "preview_table", "workspace_relative_path": "storage/generated/leads.csv"},
            {"action": "read_folder", "role": "generated"},
            {"action": "download_folder", "role": "uploaded"},
            {"action": "move_file", "role": "generated", "relative_path": "report.md"},
            {"action": "move_folder", "role": "generated", "relative_path": "Reports"},
            {"action": "move_items", "role": "generated", "files": [{"relative_path": "report.md"}]},
            {"action": "move_items", "role": "generated", "files": [], "folders": [{"relative_path": "Reports"}]},
        ]
        for payload in valid_payloads:
            with self.subTest(payload=payload):
                self.assertTrue(self.schema_accepts_payload(schema, payload))

        invalid_payloads = [
            {"action": "file_info", "role": "all", "relative_path": "report.md"},
            {"action": "read_file", "role": "all", "relative_path": "report.md"},
            {"action": "read_text", "role": "all", "relative_path": "report.md"},
            {"action": "preview_text", "role": "all", "relative_path": "report.md"},
            {"action": "upload_local_file", "workspace_relative_path": "storage/generated/output.pdf"},
            {"action": "create_folder", "role": "all", "folder_name": "Reports"},
            {"action": "move_items", "role": "all", "target_folder_relative_path": "", "files": []},
            {"action": "move_items", "role": "generated", "files": []},
            {"action": "move_items", "role": "generated", "folders": []},
            {"action": "move_items", "role": "generated", "files": [], "folders": []},
            {"action": "delete_folder", "role": "generated"},
            {"action": "move_folder", "role": "all", "relative_path": "Reports"},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                self.assertFalse(self.schema_accepts_payload(schema, payload))

    def test_backend_catalog_filters_direct_files_by_folder_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            nested = generated_root / "Reports" / "Q1"
            nested.mkdir(parents=True)
            (generated_root / "root.txt").write_text("root", encoding="utf-8")
            (generated_root / "Reports" / "summary.txt").write_text("summary", encoding="utf-8")
            (nested / "deep.txt").write_text("deep", encoding="utf-8")

            folder_page = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={
                    "action": "catalog",
                    "role": "generated",
                    "folder_path": "Reports",
                    "sort_by": "relative_path",
                    "sort_direction": "asc",
                },
            )
            root_page = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={
                    "action": "catalog",
                    "role": "generated",
                    "folder_path": "",
                    "sort_by": "relative_path",
                    "sort_direction": "asc",
                },
            )
            path_page = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={
                    "action": "catalog",
                    "workspace_relative_paths": ["storage/generated/Reports/Q1/deep.txt"],
                    "limit": 1,
                },
            )
            target_file_id = path_page["json"]["files"][0]["file_id"] if path_page["json"]["files"] else ""
            id_page = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={
                    "action": "catalog",
                    "file_ids": [target_file_id],
                    "limit": 1,
                },
            )
            escaped = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "catalog", "role": "generated", "folder_path": "../Reports"},
            )

            self.assertEqual(folder_page["status_code"], 200)
            self.assertEqual([item["relative_path"] for item in folder_page["json"]["files"]], ["Reports/summary.txt"])
            self.assertEqual(folder_page["json"]["pagination"]["total"], 1)
            self.assertEqual(root_page["status_code"], 200)
            self.assertEqual([item["relative_path"] for item in root_page["json"]["files"]], ["root.txt"])
            self.assertEqual(root_page["json"]["pagination"]["total"], 1)
            self.assertEqual(path_page["status_code"], 200)
            self.assertEqual([item["relative_path"] for item in path_page["json"]["files"]], ["Reports/Q1/deep.txt"])
            self.assertEqual(path_page["json"]["pagination"]["total"], 1)
            self.assertEqual(id_page["status_code"], 200)
            self.assertEqual([item["relative_path"] for item in id_page["json"]["files"]], ["Reports/Q1/deep.txt"])
            self.assertEqual(id_page["json"]["pagination"]["total"], 1)
            self.assertEqual(escaped["status_code"], 400)

    @unittest.skipUnless(shutil.which("libreoffice") or shutil.which("soffice"), "LibreOffice is required for rendered Office previews")
    @full_test("full storage PDF preview suite; run with scripts/test_suite.py --level full")
    def test_backend_renders_office_preview_as_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_root = root / "storage" / "generated"
            generated_root.mkdir(parents=True)
            docx = generated_root / "brief.docx"
            with zipfile.ZipFile(docx, "w") as archive:
                archive.writestr(
                    "[Content_Types].xml",
                    """<?xml version="1.0" encoding="UTF-8"?>
                    <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
                      <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
                      <Default Extension="xml" ContentType="application/xml"/>
                      <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
                    </Types>""",
                )
                archive.writestr(
                    "_rels/.rels",
                    """<?xml version="1.0" encoding="UTF-8"?>
                    <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                      <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
                    </Relationships>""",
                )
                archive.writestr(
                    "word/document.xml",
                    """<?xml version="1.0" encoding="UTF-8"?>
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                      <w:body><w:p><w:r><w:t>Quarterly brief</w:t></w:r></w:p></w:body>
                    </w:document>""",
                )

            preview = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "render_preview", "workspace_relative_path": "storage/generated/brief.docx"},
            )
            cached_preview = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "render_preview", "workspace_relative_path": "storage/generated/brief.docx"},
            )

            self.assertEqual(preview["status_code"], 200)
            self.assertEqual(preview["json"]["content_type"], "application/pdf")
            self.assertEqual(preview["json"]["preview_kind"], "pdf")
            self.assertEqual(preview["json"]["renderer"], "libreoffice")
            self.assertFalse(preview["json"]["cache_hit"])
            self.assertTrue(cached_preview["json"]["cache_hit"])
            self.assertTrue(preview["json"]["content_base64"])

            thumbnail = self.run_backend(
                data_root=root / "data" / "storage",
                uploaded_root=root / "storage" / "uploaded",
                generated_root=generated_root,
                body={"action": "render_thumbnail", "workspace_relative_path": "storage/generated/brief.docx"},
            )

            self.assertEqual(thumbnail["status_code"], 200)
            self.assertEqual(thumbnail["json"]["content_type"], "image/png")
            self.assertEqual(thumbnail["json"]["preview_kind"], "image")
            self.assertEqual(thumbnail["json"]["renderer"], "libreoffice")
            self.assertTrue(thumbnail["json"]["content_base64"])

    @integration_test("storage platform integration suite; run with scripts/test_suite.py --level integration")
    def test_bootstrap_installs_storage_and_exposes_surfaces(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        bindings = state.app_store.list_workspace_app_bindings("default")
        self.assertIn("storage", {binding.app_id for binding in bindings})
        self.assertTrue((repo_root / "workspaces" / "default" / "data" / "storage" / "state.json").is_file())

        tools = list_mcp_tools(app_store=state.app_store, workspace_id="default", start_path=repo_root)
        commands = list_core_cli_commands(app_store=state.app_store, workspace_id="default", start_path=repo_root)

        self.assertIn("app.storage.maverick_storage", [tool.tool_name for tool in tools])
        self.assertIn("app.storage.storage_list_files", [tool.tool_name for tool in tools])
        self.assertIn("app.storage.storage_read_file", [tool.tool_name for tool in tools])
        self.assertIn("app.storage.storage_read_text", [tool.tool_name for tool in tools])
        self.assertIn("app.storage.storage_write_file", [tool.tool_name for tool in tools])
        self.assertIn("app.storage.storage_image_inspect", [tool.tool_name for tool in tools])
        self.assertIn("app.storage.storage_image_compose_pair", [tool.tool_name for tool in tools])
        self.assertIn("app.storage.storage_file_localize", [tool.tool_name for tool in tools])
        self.assertNotIn("app.storage.storage_file_media_stream", [tool.tool_name for tool in tools])
        self.assertIn("app.storage.storage", [command.command_id for command in commands])
        storage_command = next(command for command in commands if command.command_id == "app.storage.storage")
        self.assertEqual(storage_command.argument_schema["properties"]["action"]["default"], "operations.manifest")
        self.assertIn("catalog", storage_command.argument_schema["properties"]["action"]["enum"])
        self.assertIn("oneOf", storage_command.argument_schema)
        action_groups = [
            entry.get("properties", {}).get("action", {}).get("enum", [])
            for entry in storage_command.argument_schema["oneOf"]
        ]
        flattened_actions = {action for group in action_groups for action in group}
        self.assertIn("file.catalog.list", flattened_actions)
        self.assertIn("image.compose_pair", flattened_actions)
        self.assertIn("file.preview.table", flattened_actions)
        self.assertIn("file.localize", flattened_actions)
        self.assertNotIn("file.media_stream", flattened_actions)
        write_tool = next(tool for tool in tools if tool.tool_name == "app.storage.storage_write_file")
        self.assertIn("workspace_relative_path", write_tool.input_schema["properties"])
        read_tool = next(tool for tool in tools if tool.tool_name == "app.storage.storage_read_file")
        self.assertNotIn("include_local_path", read_tool.input_schema["properties"])
        generic_tool = next(tool for tool in tools if tool.tool_name == "app.storage.maverick_storage")
        self.assertNotIn("include_local_path", generic_tool.input_schema["properties"])
        self.assertIn("oneOf", write_tool.input_schema)
        localize_tool = next(tool for tool in tools if tool.tool_name == "app.storage.storage_file_localize")
        self.assertIn("stable_storage_file_id", localize_tool.input_schema["properties"])
        table_tool = next(tool for tool in tools if tool.tool_name == "app.storage.storage_preview_table")
        self.assertIn("sheets", table_tool.output_schema["properties"])
        self.assertNotIn("rows", table_tool.output_schema["properties"])
        image_tool = next(tool for tool in tools if tool.tool_name == "app.storage.storage_image_compose_pair")
        self.assertNotIn("source_path", image_tool.input_schema["properties"])

    @integration_test("storage platform integration suite; run with scripts/test_suite.py --level integration")
    def test_platform_backend_and_frontend_mount_storage(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)
        generated = repo_root / "workspaces" / "default" / "storage" / "generated" / "report.txt"
        generated.parent.mkdir(parents=True, exist_ok=True)
        generated.write_text("hello", encoding="utf-8")
        clip = generated.parent / "clip.mp4"
        clip.write_bytes(b"0123456789")

        backend_status, backend_payload, _backend_headers = self.invoke(
            app,
            path="/api/apps/storage/backend",
            method="POST",
            body={"action": "catalog", "_app_secret_request": {"logical_names": [], "required": False}},
            cookie=cookie,
        )
        frontend_status, frontend_payload, frontend_headers = self.invoke(app, path="/apps/storage/", cookie=cookie)
        media_status, media_payload, media_headers = self.invoke(
            app,
            path="/api/apps/storage/media",
            cookie=cookie,
            extra_headers={"HTTP_RANGE": "bytes=2-5"},
            query_string="role=generated&relative_path=clip.mp4",
        )

        self.assertEqual(backend_status, 200)
        self.assertIn("storage/generated/report.txt", {item["workspace_relative_path"] for item in backend_payload["files"]})
        self.assertEqual(frontend_status, 200)
        self.assertIn("text/html", frontend_headers["Content-Type"])
        self.assertIn(b"Maverick Storage", frontend_payload)
        self.assertEqual(media_status, 206)
        self.assertEqual(media_payload, b"2345")
        self.assertEqual(media_headers["Accept-Ranges"], "bytes")
        self.assertEqual(media_headers["Content-Range"], "bytes 2-5/10")

    @integration_test("storage platform integration suite; run with scripts/test_suite.py --level integration")
    def test_mcp_and_cli_default_to_compact_operations_manifest(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        generated = repo_root / "workspaces" / "default" / "storage" / "generated" / "report.txt"
        generated.parent.mkdir(parents=True, exist_ok=True)
        generated.write_text("hello", encoding="utf-8")

        mcp_payload = call_mcp_tool(
            tool_name="app.storage.maverick_storage",
            context=McpInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id="tester",
                effective_mode="sandbox",
            ),
            arguments={},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )
        cli_payload = run_core_cli_command(
            command_id="app.storage.storage",
            context=CliInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id="tester",
                effective_mode="sandbox",
            ),
            arguments={},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )

        self.assertEqual(mcp_payload["status_code"], 200)
        self.assertEqual(cli_payload["status_code"], 200)
        self.assertEqual(mcp_payload["default_action"], "operations.manifest")
        self.assertEqual(cli_payload["default_action"], "operations.manifest")
        operation_by_action = {operation["action"]: operation for operation in mcp_payload["operations"]}
        self.assertEqual(operation_by_action["catalog"]["aliases"], ["file.catalog.list"])
        self.assertEqual(operation_by_action["file.text.read"]["aliases"], ["read_text"])
        self.assertEqual(operation_by_action["preview_text"]["aliases"], ["file.preview.text"])
        self.assertEqual(operation_by_action["preview_table"]["aliases"], ["file.preview.table"])
        self.assertIn("file.catalog.list", mcp_payload["payload_profiles"])
        self.assertIn("file.preview.table", mcp_payload["payload_profiles"])
        self.assertNotIn("files", mcp_payload)
        self.assertNotIn("files", cli_payload)

    @integration_test("storage platform integration suite; run with scripts/test_suite.py --level integration")
    def test_mcp_and_cli_call_storage_catalog(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        uploaded = repo_root / "workspaces" / "default" / "storage" / "uploaded" / "source.txt"
        uploaded.parent.mkdir(parents=True, exist_ok=True)
        uploaded.write_text("source", encoding="utf-8")

        mcp_payload = call_mcp_tool(
            tool_name="app.storage.maverick_storage",
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
        dedicated_payload = call_mcp_tool(
            tool_name="app.storage.storage_list_files",
            context=McpInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id="tester",
                effective_mode="sandbox",
            ),
            arguments={"limit": 10},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )
        cli_payload = run_core_cli_command(
            command_id="app.storage.storage",
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
        self.assertEqual(dedicated_payload["status_code"], 200)
        self.assertEqual(cli_payload["status_code"], 200)
        self.assertEqual(mcp_payload["files"][0]["workspace_relative_path"], "storage/uploaded/source.txt")
        self.assertEqual(dedicated_payload["files"][0]["workspace_relative_path"], "storage/uploaded/source.txt")
        self.assertEqual(cli_payload["files"][0]["workspace_relative_path"], "storage/uploaded/source.txt")

    @integration_test("storage platform integration suite; run with scripts/test_suite.py --level integration")
    def test_mcp_dedicated_file_tools_execute_end_to_end(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        generated = repo_root / "workspaces" / "default" / "storage" / "generated"
        generated.mkdir(parents=True, exist_ok=True)
        (generated / "report.md").write_text("# Report\n\nhello from storage\n", encoding="utf-8")
        (generated / "leads.csv").write_text("name,value\nAcme,42\nGlobex,7\n", encoding="utf-8")
        context = McpInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="tester",
            effective_mode="sandbox",
        )

        info_payload = call_mcp_tool(
            tool_name="app.storage.storage_file_info",
            context=context,
            arguments={"workspace_relative_path": "storage/generated/report.md"},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )
        read_payload = call_mcp_tool(
            tool_name="app.storage.storage_read_file",
            context=context,
            arguments={"workspace_relative_path": "storage/generated/report.md"},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )
        text_read = call_mcp_tool(
            tool_name="app.storage.storage_read_text",
            context=context,
            arguments={"workspace_relative_path": "storage/generated/report.md"},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )
        text_preview = call_mcp_tool(
            tool_name="app.storage.storage_preview_text",
            context=context,
            arguments={"workspace_relative_path": "storage/generated/report.md", "max_chars": 80},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )
        table_preview = call_mcp_tool(
            tool_name="app.storage.storage_preview_table",
            context=context,
            arguments={"workspace_relative_path": "storage/generated/leads.csv", "max_rows": 5, "max_columns": 5},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )

        self.assertEqual(info_payload["status_code"], 200)
        self.assertEqual(info_payload["file"]["workspace_relative_path"], "storage/generated/report.md")
        self.assertEqual(read_payload["status_code"], 200)
        self.assertIn("# Report", b64decode(read_payload["content_base64"]).decode("utf-8"))
        self.assertEqual(text_read["status_code"], 200)
        self.assertIn("hello from storage", text_read["text"])
        self.assertTrue(text_read["complete"])
        self.assertEqual(text_preview["status_code"], 200)
        self.assertIn("hello from storage", text_preview["preview_text"])
        self.assertEqual(table_preview["status_code"], 200)
        self.assertEqual(table_preview["file"]["workspace_relative_path"], "storage/generated/leads.csv")
        self.assertEqual(table_preview["sheets"][0]["rows"][0], ["name", "value"])
        self.assertEqual(table_preview["sheets"][0]["rows"][1], ["Acme", "42"])

    @integration_test("storage platform integration suite; run with scripts/test_suite.py --level integration")
    def test_mcp_and_cli_can_write_storage_file_content(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        generated = repo_root / "workspaces" / "default" / "storage" / "generated"
        generated.mkdir(parents=True, exist_ok=True)

        mcp_payload = call_mcp_tool(
            tool_name="app.storage.storage_write_file",
            context=McpInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id="tester",
                effective_mode="sandbox",
            ),
            arguments={
                "role": "generated",
                "relative_path": "fleet/mcp-output.txt",
                "mode": "create",
                "content": "mcp output",
            },
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )
        cli_payload = run_core_cli_command(
            command_id="app.storage.storage",
            context=CliInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id="tester",
                effective_mode="sandbox",
            ),
            arguments={
                "action": "write",
                "workspace_relative_path": "storage/generated/fleet/mcp-output.txt",
                "mode": "overwrite",
                "confirm": True,
                "content": "cli output",
            },
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )

        self.assertEqual(mcp_payload["status_code"], 200)
        self.assertEqual(cli_payload["status_code"], 200)
        self.assertEqual((generated / "fleet" / "mcp-output.txt").read_text(encoding="utf-8"), "cli output")

    @integration_test("storage platform integration suite; run with scripts/test_suite.py --level integration")
    def test_cli_can_update_storage_view_filter(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        updated = run_core_cli_command(
            command_id="app.storage.storage",
            context=CliInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id="tester",
                effective_mode="sandbox",
            ),
            arguments={"action": "set_view_filter", "query": "Acme", "role": "generated", "kind": "document"},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )
        catalog = run_core_cli_command(
            command_id="app.storage.storage",
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
        self.assertEqual(catalog["state"]["view_filter"]["query"], "Acme")
        self.assertEqual(catalog["state"]["view_filter"]["role"], "generated")
        self.assertEqual(catalog["state"]["view_filter"]["kind"], "document")

    @integration_test("storage platform integration suite; run with scripts/test_suite.py --level integration")
    def test_cli_can_read_storage_view_filter_without_catalog_scan(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        run_core_cli_command(
            command_id="app.storage.storage",
            context=CliInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id="tester",
                effective_mode="sandbox",
            ),
            arguments={"action": "set_view_filter", "query": "Acme"},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )
        view_filter = run_core_cli_command(
            command_id="app.storage.storage",
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
        self.assertEqual(view_filter["state"]["view_filter"]["query"], "Acme")
        self.assertNotIn("files", view_filter)

    @integration_test("storage platform integration suite; run with scripts/test_suite.py --level integration")
    def test_cli_can_set_storage_custom_view(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        custom = run_core_cli_command(
            command_id="app.storage.storage",
            context=CliInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id="tester",
                effective_mode="sandbox",
            ),
            arguments={
                "action": "set_custom_view",
                "title": "Topic files",
                "file_ids": ["generated:memory_app_checklist.md", "generated:company_profile.docx"],
            },
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )

        self.assertEqual(custom["status_code"], 200)
        self.assertEqual(custom["state"]["view_filter"]["mode"], "custom")
        self.assertEqual(custom["state"]["view_filter"]["title"], "Topic files")
        self.assertEqual(
            custom["state"]["view_filter"]["file_ids"],
            ["generated:memory_app_checklist.md", "generated:company_profile.docx"],
        )


if __name__ == "__main__":
    unittest.main()
