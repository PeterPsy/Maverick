"""Website Studio service tests."""

from __future__ import annotations

import base64
import json
import os
from io import BytesIO
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

APP_ROOT = Path(__file__).resolve().parents[1]
MAVERICK_ROOT = APP_ROOT.parents[3]
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(APP_ROOT / "backend"))

from backend.service import handle_action
from safety import MAX_SOURCE_TREE_FILES, validate_source_tree_for_phase1


class WebsiteStudioEntrypointTest(unittest.TestCase):
    def test_site_edit_diff_and_publish_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Acme"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]

            status, map_payload = handle_action(data_root, {"action": "sitemap", "site_id": site_id})
            self.assertEqual(status, 200)
            self.assertEqual(map_payload["items"][0]["route"], "/")

            status, read_payload = handle_action(data_root, {"action": "read_file", "site_id": site_id, "path": "index.html"})
            self.assertEqual(status, 200)
            original_hash = read_payload["file"]["hash"]

            status, write_payload = handle_action(
                data_root,
                {
                    "action": "write_file",
                    "site_id": site_id,
                    "path": "index.html",
                    "content": read_payload["file"]["content"].replace("Acme", "Acme Studio", 1),
                    "expected_hash": original_hash,
                },
            )
            self.assertEqual(status, 200)
            self.assertIn("changeset", write_payload)

            status, stale = handle_action(
                data_root,
                {
                    "action": "write_file",
                    "site_id": site_id,
                    "path": "index.html",
                    "content": "stale",
                    "expected_hash": original_hash,
                },
            )
            self.assertEqual(status, 400)
            self.assertIn("stale write", stale["detail"])

            status, diff = handle_action(data_root, {"action": "diff", "site_id": site_id})
            self.assertEqual(status, 200)
            self.assertEqual(diff["files"][0]["path"], "index.html")

            status, blocked = handle_action(data_root, {"action": "publish", "site_id": site_id})
            self.assertEqual(status, 403)
            self.assertTrue(blocked["blocked"])

    def test_zip_import_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("../escape.html", "<html></html>")
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")

            status, result = handle_action(
                Path(tmp),
                {"action": "import_zip", "display_name": "Unsafe", "archive_base64": encoded},
            )
            self.assertEqual(status, 400)
            self.assertIn("unsafe path", result["detail"].lower())

    def test_zip_import_rejects_invalid_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            encoded = base64.b64encode(b"not a zip").decode("ascii")

            status, result = handle_action(
                Path(tmp),
                {"action": "import_zip", "display_name": "Invalid", "archive_base64": encoded},
            )

            self.assertEqual(status, 400)
            self.assertIn("valid zip", result["detail"].lower())

    def test_zip_import_rejects_executable_and_sensitive_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("index.html", "<title>Site</title>")
                zip_file.writestr(".env", "SECRET=value")
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")

            status, result = handle_action(
                Path(tmp),
                {"action": "import_zip", "display_name": "Unsafe", "archive_base64": encoded},
            )

            self.assertEqual(status, 400)
            self.assertIn("sensitive file", result["detail"])

    def test_git_import_indexes_site(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            repo_root = data_root / "fixtures" / "repo"
            repo_root.mkdir(parents=True)
            (repo_root / "index.html").write_text("<title>Git Site</title><main>Imported</main>", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "agent@example.com"], cwd=repo_root, check=True)
            subprocess.run(["git", "config", "user.name", "Agent"], cwd=repo_root, check=True)
            subprocess.run(["git", "add", "index.html"], cwd=repo_root, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_root, check=True, capture_output=True, text=True)

            status, result = handle_action(
                data_root,
                {"action": "import_git", "repository_url": str(repo_root), "display_name": "Git Site"},
            )

            self.assertEqual(status, 201)
            self.assertEqual(result["site"]["source_provider"], "git")
            self.assertIn("revision", result)

            status, map_payload = handle_action(data_root, {"action": "sitemap", "site_id": result["site"]["id"]})
            self.assertEqual(status, 200)
            self.assertEqual(map_payload["items"][0]["route"], "/")

    def test_git_import_rejects_inline_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, result = handle_action(
                Path(tmp),
                {"action": "import_git", "repository_url": "https://user:secret@example.com/repo.git"},
            )

            self.assertEqual(status, 400)
            self.assertIn("inline credentials", result["detail"])

    def test_git_import_rejects_non_github_remote_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, result = handle_action(
                Path(tmp),
                {"action": "import_git", "repository_url": "ssh://example.com/company/site.git"},
            )

            self.assertEqual(status, 400)
            self.assertIn("GitHub HTTPS", result["detail"])

    def test_write_rejects_site_id_escape_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            outside = Path(tmp) / "escape" / "source" / "pwn.txt"

            status, result = handle_action(
                data_root,
                {"action": "write_file", "site_id": "../../escape", "path": "pwn.txt", "content": "outside write"},
            )

            self.assertEqual(status, 400)
            self.assertIn("not found", result["detail"])
            self.assertFalse(outside.exists())

    def test_write_and_patch_require_expected_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Acme"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]

            status, result = handle_action(
                data_root,
                {"action": "write_file", "site_id": site_id, "path": "index.html", "content": "overwrite"},
            )
            self.assertEqual(status, 400)
            self.assertIn("expected_hash is required", result["detail"])

            status, result = handle_action(
                data_root,
                {
                    "action": "apply_patch",
                    "site_id": site_id,
                    "path": "index.html",
                    "old_text": "Acme",
                    "new_text": "Acme Studio",
                },
            )
            self.assertEqual(status, 400)
            self.assertIn("expected_hash is required", result["detail"])

            status, created_file = handle_action(
                data_root,
                {
                    "action": "write_file",
                    "site_id": site_id,
                    "path": "new-page.html",
                    "content": "<title>New</title>",
                    "expected_hash": "new",
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(created_file["file"]["path"], "new-page.html")

    def test_write_rejects_sensitive_executable_and_unsupported_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Acme"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]

            for rel_path, expected_detail in (
                (".env", "sensitive file"),
                ("deploy.sh", "executable file"),
                ("README", "not a supported Website Studio text file"),
            ):
                status, result = handle_action(
                    data_root,
                    {
                        "action": "write_file",
                        "site_id": site_id,
                        "path": rel_path,
                        "content": "blocked",
                        "expected_hash": "new",
                    },
                )
                self.assertEqual(status, 400)
                self.assertIn(expected_detail, result["detail"])

    def test_zip_reimport_failure_keeps_existing_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Acme"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            starter = data_root / "sites" / site_id / "source" / "index.html"
            self.assertTrue(starter.exists())

            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("../escape.html", "<html></html>")
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")

            status, result = handle_action(data_root, {"action": "import_zip", "site_id": site_id, "archive_base64": encoded})

            self.assertEqual(status, 400)
            self.assertIn("unsafe path", result["detail"].lower())
            self.assertTrue(starter.exists())

    def test_git_reimport_failure_keeps_existing_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Acme"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            starter = data_root / "sites" / site_id / "source" / "index.html"
            original = starter.read_text(encoding="utf-8")

            repo_root = data_root / "fixtures" / "unsafe-repo"
            repo_root.mkdir(parents=True)
            (repo_root / "index.html").write_text("<title>Unsafe</title>", encoding="utf-8")
            (repo_root / ".env").write_text("SECRET=value", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "agent@example.com"], cwd=repo_root, check=True)
            subprocess.run(["git", "config", "user.name", "Agent"], cwd=repo_root, check=True)
            subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
            subprocess.run(["git", "commit", "-m", "unsafe"], cwd=repo_root, check=True, capture_output=True, text=True)

            status, result = handle_action(
                data_root,
                {"action": "import_git", "site_id": site_id, "repository_url": str(repo_root)},
            )

            self.assertEqual(status, 400)
            self.assertIn("sensitive file", result["detail"])
            self.assertEqual(starter.read_text(encoding="utf-8"), original)

    def test_source_tree_validation_rejects_excessive_file_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp)
            for index in range(MAX_SOURCE_TREE_FILES + 1):
                (source_root / f"page-{index}.html").write_text("<title>Page</title>", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "too many files"):
                validate_source_tree_for_phase1(source_root)

    def test_publish_with_unverified_approval_stays_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Acme"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            status, request_payload = handle_action(data_root, {"action": "publish_request", "site_id": site_id})
            self.assertEqual(status, 201)

            status, publish_payload = handle_action(
                data_root,
                {
                    "action": "publish",
                    "site_id": site_id,
                    "publish_request_id": request_payload["publish_request"]["id"],
                    "approval_id": "not-a-verified-approval",
                },
            )

            self.assertEqual(status, 403)
            self.assertTrue(publish_payload["blocked"])
            self.assertIn("official approval surface", publish_payload["detail"])

    def test_rollback_restores_binary_assets_from_revision_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("index.html", "<title>Imported</title>")
                zip_file.writestr("assets/logo.png", b"\x89PNG\r\nphase1")
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")

            status, imported = handle_action(
                data_root,
                {"action": "import_zip", "display_name": "Imported", "archive_base64": encoded},
            )
            self.assertEqual(status, 201)
            site_id = imported["site"]["id"]
            revision_id = imported["revision"]["id"]
            logo = data_root / "sites" / site_id / "source" / "assets" / "logo.png"
            logo.unlink()

            status, rolled_back = handle_action(
                data_root,
                {
                    "action": "rollback",
                    "site_id": site_id,
                    "revision_id": revision_id,
                    "approval_id": "approval_phase1_local",
                    "confirm": True,
                },
            )

            self.assertEqual(status, 200)
            self.assertEqual(rolled_back["site"]["id"], site_id)
            self.assertEqual(logo.read_bytes(), b"\x89PNG\r\nphase1")

    def test_rollback_requires_policy_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Acme"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            revision_id = created["site"]["active_revision_id"]

            status, blocked = handle_action(data_root, {"action": "rollback", "site_id": site_id, "revision_id": revision_id})

            self.assertEqual(status, 403)
            self.assertTrue(blocked["blocked"])
            self.assertIn("approval_id", blocked["detail"])

    def test_zip_import_indexes_routes_assets_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr(
                    "index.html",
                    '<title>Imported</title><link rel="stylesheet" href="assets/site.css"><img src="assets/logo.png"><img src="missing.png">',
                )
                zip_file.writestr("about/index.html", "<title>About</title>")
                zip_file.writestr("assets/site.css", "body { color: #111; }")
                zip_file.writestr("assets/logo.png", b"\x89PNG\r\nphase1")
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")
            artifact_ref = {
                "app_id": "storage",
                "file_id": "file_zip",
                "workspace_relative_path": "storage/uploaded/website-studio/imported.zip",
            }

            status, imported = handle_action(
                data_root,
                {
                    "action": "import_zip",
                    "display_name": "Imported",
                    "archive_base64": encoded,
                    "source_artifact_ref": artifact_ref,
                },
            )

            self.assertEqual(status, 201)
            self.assertEqual(imported["import"]["source_shape"], "static_export")
            self.assertEqual(imported["site"]["source_artifact_ref"]["file_id"], "file_zip")

            status, map_payload = handle_action(data_root, {"action": "sitemap", "site_id": imported["site"]["id"]})
            self.assertEqual(status, 200)
            self.assertEqual({item["route"] for item in map_payload["routes"]}, {"/", "/about"})
            self.assertEqual({asset["path"] for asset in map_payload["assets"]}, {"assets/logo.png", "assets/site.css"})
            home = next(item for item in map_payload["items"] if item["route"] == "/")
            self.assertIn("assets/logo.png", home["asset_refs"])
            self.assertIn("missing asset `missing.png`", home["warnings"])

    def test_preview_html_is_sandbox_prepared(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Acme"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            status, read_payload = handle_action(data_root, {"action": "read_file", "site_id": site_id, "path": "index.html"})
            self.assertEqual(status, 200)
            status, _ = handle_action(
                data_root,
                {
                    "action": "write_file",
                    "site_id": site_id,
                    "path": "index.html",
                    "content": "<!doctype html><title>X</title><button onclick=\"alert(1)\">x</button><script>alert(1)</script>",
                    "expected_hash": read_payload["file"]["hash"],
                },
            )
            self.assertEqual(status, 200)

            status, preview = handle_action(data_root, {"action": "build_preview", "site_id": site_id})

            self.assertEqual(status, 200)
            self.assertIn("Content-Security-Policy", preview["html"])
            self.assertNotIn("<script", preview["html"].lower())
            self.assertNotIn("onclick", preview["html"].lower())

    def test_preview_inlines_static_css_and_image_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("index.html", '<title>Preview</title><link rel="stylesheet" href="assets/site.css"><img src="assets/logo.png">')
                zip_file.writestr("assets/site.css", "body { color: #111; }")
                zip_file.writestr("assets/logo.png", b"\x89PNG\r\nphase1")
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")

            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "Preview", "archive_base64": encoded})
            self.assertEqual(status, 201)
            status, preview = handle_action(data_root, {"action": "build_preview", "site_id": imported["site"]["id"]})

            self.assertEqual(status, 200)
            self.assertIn("<style>body { color: #111; }</style>", preview["html"])
            self.assertIn("data:image/png;base64,", preview["html"])

    def test_active_context_includes_route_assets_and_change_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Acme"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            status, context = handle_action(data_root, {"action": "active_context", "site_id": site_id})

            self.assertEqual(status, 200)
            self.assertEqual(context["active_view"], "page")
            self.assertEqual(context["site_id"], site_id)
            self.assertIn("routes", context)
            self.assertIn("assets", context)
            self.assertIn("changed_files_count", context)

    def test_reference_manifest_and_search_match_declared_entities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Acme"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            status, _ = handle_action(data_root, {"action": "publish_request", "site_id": site_id})
            self.assertEqual(status, 201)

            status, manifest = handle_action(data_root, {"action": "reference_manifest"})
            self.assertEqual(status, 200)
            searchable = {item["entity_type"]: item["searchable"] for item in manifest["entity_types"]}
            self.assertFalse(searchable["revision"])
            self.assertTrue(searchable["publish_request"])

            status, results = handle_action(data_root, {"action": "reference_search", "query": "pending"})
            self.assertEqual(status, 200)
            self.assertIn("publish_request", {item["entity_type"] for item in results["items"]})

    def test_cli_default_lists_sites(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = {
                "app_id": "website-studio",
                "workspace_id": "default",
                "data_root": tmp,
                "arguments": {},
            }

            result = subprocess.run(
                [sys.executable, str(APP_ROOT / "cli" / "app_cli.py")],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=True,
                cwd=APP_ROOT,
                env={**os.environ, "PYTHONPATH": str(MAVERICK_ROOT)},
            )

            parsed = json.loads(result.stdout)
            self.assertEqual(parsed["status_code"], 200)
            self.assertEqual(parsed["items"], [])

    def test_sitemap_widget_avoids_route_html_interpolation(self) -> None:
        widget_source = (APP_ROOT / "frontend" / "public" / "widgets" / "website-studio-sitemap-sidebar" / "index.html").read_text(encoding="utf-8")

        self.assertNotIn('data-route="${page.route}"', widget_source)
        self.assertNotIn("list.innerHTML = filtered.map", widget_source)
        self.assertIn("document.createElement('button')", widget_source)


if __name__ == "__main__":
    unittest.main()
