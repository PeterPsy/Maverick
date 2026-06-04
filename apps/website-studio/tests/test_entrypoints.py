"""Website Studio service tests."""

from __future__ import annotations

import base64
import json
import multiprocessing
import os
from io import BytesIO
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from zipfile import ZipFile

APP_ROOT = Path(__file__).resolve().parents[1]
MAVERICK_ROOT = APP_ROOT.parents[3]
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(APP_ROOT / "backend"))

from backend.service import app_events_for_action, handle_action
from backend.store import _site_mutation_lock
from safety import MAX_SOURCE_TREE_FILES, validate_source_tree_for_phase1


class FakeGitHubTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def __call__(self, method: str, url: str, request: dict[str, object]) -> tuple[int, object]:
        self.calls.append((method, url, request))
        if method == "GET" and "/git/ref/heads/main" in url:
            return 200, {"object": {"sha": "base-sha"}}
        if method == "GET" and "/git/commits/base-sha" in url:
            return 200, {"tree": {"sha": "base-tree-sha"}}
        if method == "POST" and url.endswith("/git/blobs"):
            return 201, {"sha": f"blob-{len([call for call in self.calls if call[1].endswith('/git/blobs')])}"}
        if method == "POST" and url.endswith("/git/trees"):
            return 201, {"sha": "tree-sha"}
        if method == "POST" and url.endswith("/git/commits"):
            return 201, {"sha": "commit-sha"}
        if method == "GET" and "/git/ref/heads/maverick%2F" in url:
            return 404, {}
        if method == "POST" and url.endswith("/git/refs"):
            return 201, {"ref": "refs/heads/maverick/site/test"}
        if method == "GET" and "/pulls?" in url:
            return 200, []
        if method == "POST" and url.endswith("/pulls"):
            return 201, {"number": 42, "html_url": "https://github.com/example-org/site-web/pull/42"}
        return 500, {"message": f"unexpected fake GitHub request {method} {url}"}


def _write_with_expected_hash_worker(data_root: str, site_id: str, expected_hash: str, queue) -> None:
    status, result = handle_action(
        Path(data_root),
        {
            "action": "write_file",
            "site_id": site_id,
            "path": "index.html",
            "content": "<title>Concurrent</title>",
            "expected_hash": expected_hash,
        },
    )
    queue.put((status, result.get("detail", "")))


def _edit_index(data_root: Path, site_id: str, marker: str = "Edited") -> None:
    status, read_payload = handle_action(data_root, {"action": "read_file", "site_id": site_id, "path": "index.html"})
    if status != 200:
        raise AssertionError(read_payload)
    status, write_payload = handle_action(
        data_root,
        {
            "action": "write_file",
            "site_id": site_id,
            "path": "index.html",
            "content": read_payload["file"]["content"].replace("</main>", f"<p>{marker}</p></main>", 1),
            "expected_hash": read_payload["file"]["hash"],
        },
    )
    if status != 200:
        raise AssertionError(write_payload)


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

    def test_site_lifecycle_archive_restore_rename_and_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Acme"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]

            status, renamed = handle_action(
                data_root,
                {"action": "site_rename", "site_id": site_id, "display_name": "Acme Studio", "slug": "acme"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(renamed["site"]["display_name"], "Acme Studio")
            self.assertEqual(renamed["site"]["slug"], "acme")

            status, archived = handle_action(data_root, {"action": "site_archive", "site_id": site_id})
            self.assertEqual(status, 200)
            self.assertEqual(archived["site"]["status"], "archived")
            self.assertTrue(archived["site"]["archived_at"])

            status, restored = handle_action(data_root, {"action": "site_restore", "site_id": site_id})
            self.assertEqual(status, 200)
            self.assertEqual(restored["site"]["status"], "draft")
            self.assertIsNone(restored["site"]["archived_at"])

            status, duplicated = handle_action(
                data_root,
                {"action": "site_duplicate", "site_id": site_id, "display_name": "Acme Clone", "slug": "acme"},
            )
            self.assertEqual(status, 201)
            self.assertNotEqual(duplicated["site"]["id"], site_id)
            self.assertEqual(duplicated["site"]["slug"], "acme-2")
            self.assertTrue((data_root / "sites" / duplicated["site"]["id"] / "source" / "index.html").exists())

    def test_active_site_selection_persists_for_context_and_listing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, first = handle_action(data_root, {"action": "site_create", "display_name": "Acme"})
            self.assertEqual(status, 201)
            status, second = handle_action(data_root, {"action": "site_create", "display_name": "Beta"})
            self.assertEqual(status, 201)

            status, selected = handle_action(data_root, {"action": "site_set_active", "site_id": first["site"]["id"]})
            self.assertEqual(status, 200)
            self.assertEqual(selected["state"]["active_site_id"], first["site"]["id"])
            self.assertTrue(selected["site"]["is_active"])

            status, listed = handle_action(data_root, {"action": "sites_list"})
            self.assertEqual(status, 200)
            active = [item["id"] for item in listed["items"] if item["is_active"]]
            self.assertEqual(active, [first["site"]["id"]])

            status, context = handle_action(data_root, {"action": "active_context"})
            self.assertEqual(status, 200)
            self.assertEqual(context["site_id"], first["site"]["id"])

            status, archived = handle_action(data_root, {"action": "site_archive", "site_id": first["site"]["id"]})
            self.assertEqual(status, 200)
            self.assertEqual(archived["site"]["status"], "archived")
            status, blocked = handle_action(data_root, {"action": "site_set_active", "site_id": first["site"]["id"]})
            self.assertEqual(status, 400)
            self.assertIn("archived sites", blocked["detail"])

            status, context = handle_action(data_root, {"action": "active_context"})
            self.assertEqual(status, 200)
            self.assertEqual(context["site_id"], second["site"]["id"])

    def test_active_context_ignores_archived_sites_when_state_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Archived"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]

            status, archived = handle_action(data_root, {"action": "site_archive", "site_id": site_id})
            self.assertEqual(status, 200)
            self.assertEqual(archived["site"]["status"], "archived")
            (data_root / "view_state.json").write_text(
                json.dumps({"schema_version": "1", "active_site_id": site_id, "view_filter": {"mode": "search"}}),
                encoding="utf-8",
            )

            status, listed = handle_action(data_root, {"action": "sites_list"})
            self.assertEqual(status, 200)
            self.assertFalse(listed["items"][0]["is_active"])

            status, context = handle_action(data_root, {"action": "active_context"})
            self.assertEqual(status, 200)
            self.assertEqual(context["active_view"], "empty")
            self.assertIsNone(context["site_id"])

            status, explicit_context = handle_action(data_root, {"action": "page_context", "site_id": site_id})
            self.assertEqual(status, 200)
            self.assertEqual(explicit_context["active_view"], "empty")

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
            (repo_root / "package.json").write_text('{"scripts":{"build":"vite build"}}', encoding="utf-8")
            (repo_root / "vite.config.ts").write_text("export default {}\n", encoding="utf-8")
            (repo_root / "package-lock.json").write_text("{}", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "agent@example.com"], cwd=repo_root, check=True)
            subprocess.run(["git", "config", "user.name", "Agent"], cwd=repo_root, check=True)
            subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_root, check=True, capture_output=True, text=True)

            status, result = handle_action(
                data_root,
                {"action": "import_git", "repository_url": str(repo_root), "display_name": "Git Site"},
            )

            self.assertEqual(status, 201)
            self.assertEqual(result["site"]["source_provider"], "git")
            self.assertEqual(result["import"]["source_shape"], "full_source")
            self.assertEqual(result["import"]["source_profile"]["framework"], "vite")
            self.assertEqual(result["import"]["source_profile"]["package_manager"], "npm")
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

    def test_git_connection_prepare_records_repo_and_vault_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, prepared = handle_action(
                data_root,
                {
                    "action": "git_connection_prepare",
                    "repository_url": "example-org/site-web",
                    "base_branch": "main",
                    "auth_mode": "fine_grained_token",
                },
            )

            self.assertEqual(status, 201)
            self.assertEqual(prepared["connection"]["owner"], "example-org")
            self.assertEqual(prepared["connection"]["repo"], "site-web")
            self.assertEqual(prepared["connection"]["repository_url"], "https://github.com/example-org/site-web.git")
            self.assertEqual(prepared["connection"]["status"], "pending_vault_grant")
            self.assertEqual(prepared["connection"]["secret_logical_name"], "github-token")
            self.assertTrue(prepared["connection"]["secret_configured"])
            self.assertEqual(prepared["vault_requirements"]["required_secrets"], ["github-token"])
            self.assertNotIn("private_key", json.dumps(prepared).lower())
            self.assertTrue(prepared["site"]["is_active"])

            status, listed = handle_action(data_root, {"action": "git_connections_list", "site_id": prepared["site"]["id"]})
            self.assertEqual(status, 200)
            self.assertEqual(listed["items"][0]["id"], prepared["connection"]["id"])

    def test_git_connection_prepare_defaults_to_fine_grained_token_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, prepared = handle_action(
                Path(tmp),
                {
                    "action": "git_connection_prepare",
                    "repository_url": "https://github.com/example-org/site-web.git",
                },
            )

            self.assertEqual(status, 201)
            self.assertEqual(prepared["connection"]["secret_logical_name"], "github-token")
            self.assertEqual(prepared["vault_requirements"]["required_secrets"], ["github-token"])

    def test_git_connection_prepare_rejects_raw_or_invalid_secret_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for payload, expected in (
                ({"repository_url": "https://user:secret@github.com/example-org/site-web.git"}, "inline credentials"),
                ({"repository_url": "example-org/site-web", "auth_mode": "unsupported"}, "auth_mode"),
                ({"repository_url": "example-org/site-web", "auth_mode": "github_app"}, "auth_mode"),
                ({"repository_url": "example-org/site-web", "secret_logical_name": "not-declared"}, "secret_logical_name"),
            ):
                status, result = handle_action(Path(tmp), {"action": "git_connection_prepare", **payload})
                self.assertEqual(status, 400)
                self.assertIn(expected, result["detail"])

    def test_git_import_rejects_executable_mode_without_blocked_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            repo_root = data_root / "fixtures" / "executable-repo"
            repo_root.mkdir(parents=True)
            (repo_root / "index.html").write_text("<title>Safe</title>", encoding="utf-8")
            runner = repo_root / "runner"
            runner.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            runner.chmod(0o755)
            subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "agent@example.com"], cwd=repo_root, check=True)
            subprocess.run(["git", "config", "user.name", "Agent"], cwd=repo_root, check=True)
            subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
            subprocess.run(["git", "commit", "-m", "executable"], cwd=repo_root, check=True, capture_output=True, text=True)

            status, result = handle_action(
                data_root,
                {"action": "import_git", "repository_url": str(repo_root), "display_name": "Executable Site"},
            )

            self.assertEqual(status, 400)
            self.assertIn("executable file", result["detail"])

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

    def test_concurrent_write_checks_hash_after_site_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Acme"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            status, read_payload = handle_action(data_root, {"action": "read_file", "site_id": site_id, "path": "index.html"})
            self.assertEqual(status, 200)

            ctx = multiprocessing.get_context("fork")
            queue = ctx.Queue()
            process = ctx.Process(target=_write_with_expected_hash_worker, args=(str(data_root), site_id, read_payload["file"]["hash"], queue))
            source_file = data_root / "sites" / site_id / "source" / "index.html"
            with _site_mutation_lock(data_root, site_id):
                process.start()
                time.sleep(0.2)
                source_file.write_text("<title>Parent change</title>", encoding="utf-8")
            process.join(5)

            self.assertFalse(process.is_alive())
            worker_status, worker_detail = queue.get_nowait()
            self.assertEqual(worker_status, 400)
            self.assertIn("stale write", worker_detail)
            self.assertEqual(source_file.read_text(encoding="utf-8"), "<title>Parent change</title>")

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
            _edit_index(data_root, site_id)
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

    def test_publish_request_requires_working_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Acme"})
            self.assertEqual(status, 201)

            status, result = handle_action(data_root, {"action": "publish_request", "site_id": created["site"]["id"]})

            self.assertEqual(status, 400)
            self.assertIn("at least one working file change", result["detail"])

    def test_list_changes_reports_diff_revisions_and_publish_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Acme"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            _edit_index(data_root, site_id)
            status, request_payload = handle_action(data_root, {"action": "publish_request", "site_id": site_id})
            self.assertEqual(status, 201)

            status, changes = handle_action(data_root, {"action": "list_changes", "site_id": site_id})

            self.assertEqual(status, 200)
            self.assertEqual(changes["working_diff"][0]["path"], "index.html")
            self.assertEqual(changes["changesets"][0]["files_changed_count"], 1)
            self.assertEqual(changes["publish_requests"][0]["id"], request_payload["publish_request"]["id"])
            self.assertEqual(changes["revisions"][0]["id"], created["site"]["active_revision_id"])

    def test_rollback_with_unverified_approval_stays_blocked(self) -> None:
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

            self.assertEqual(status, 403)
            self.assertTrue(rolled_back["blocked"])
            self.assertIn("official approval surface", rolled_back["detail"])
            self.assertFalse(logo.exists())

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

    def test_zip_import_collapses_single_root_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("site-export/index.html", "<title>Nested Export</title>")
                zip_file.writestr("site-export/assets/site.css", "body { color: #111; }")
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")

            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "Nested", "archive_base64": encoded})
            self.assertEqual(status, 201)
            site_id = imported["site"]["id"]

            self.assertTrue((data_root / "sites" / site_id / "source" / "index.html").exists())
            self.assertFalse((data_root / "sites" / site_id / "source" / "site-export" / "index.html").exists())
            status, map_payload = handle_action(data_root, {"action": "sitemap", "site_id": site_id})
            self.assertEqual(status, 200)
            self.assertEqual(map_payload["items"][0]["route"], "/")

    def test_root_relative_assets_are_indexed_and_inlined_in_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("about/index.html", '<title>About</title><link rel="stylesheet" href="/assets/site.css"><img src="/assets/logo.png">')
                zip_file.writestr("assets/site.css", "body { color: #111; }")
                zip_file.writestr("assets/logo.png", b"\x89PNG\r\nphase1")
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")

            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "Root Relative", "archive_base64": encoded})
            self.assertEqual(status, 201)
            status, map_payload = handle_action(data_root, {"action": "sitemap", "site_id": imported["site"]["id"]})
            self.assertEqual(status, 200)
            page = map_payload["items"][0]
            self.assertEqual(page["route"], "/about")
            self.assertIn("assets/logo.png", page["asset_refs"])
            self.assertFalse(page["warnings"])

            status, preview = handle_action(data_root, {"action": "build_preview", "site_id": imported["site"]["id"], "route": "/about"})
            self.assertEqual(status, 200)
            self.assertIn("<style>body { color: #111; }</style>", preview["html"])
            self.assertIn("data:image/png;base64,", preview["html"])

    def test_zip_import_reports_source_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("index.html", "<title>Profiled</title>")
                zip_file.writestr("astro.config.mjs", "export default {}")
                zip_file.writestr("package.json", '{"scripts":{"build":"astro build"}}')
                zip_file.writestr("pnpm-lock.yaml", "lockfileVersion: '9.0'")
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")

            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "Profiled", "archive_base64": encoded})
            self.assertEqual(status, 201)
            self.assertEqual(imported["import"]["source_profile"]["source_shape"], "full_source")
            self.assertEqual(imported["import"]["source_profile"]["framework"], "astro")
            self.assertEqual(imported["import"]["source_profile"]["package_manager"], "pnpm")
            self.assertEqual(imported["site"]["source_shape"], "full_source")

    def test_sitemap_index_includes_xml_redirects_and_seo_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr(
                    "index.html",
                    (
                        "<title>Imported</title>"
                        '<meta name="description" content="Primary page">'
                        '<meta property="og:title" content="OG imported">'
                        '<link rel="canonical" href="https://example.com/">'
                    ),
                )
                zip_file.writestr(
                    "sitemap.xml",
                    """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/missing</loc></url>
</urlset>
""",
                )
                zip_file.writestr("_redirects", "/old /new 302\n")
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")

            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "Indexed", "archive_base64": encoded})
            self.assertEqual(status, 201)
            status, map_payload = handle_action(data_root, {"action": "sitemap", "site_id": imported["site"]["id"]})

            self.assertEqual(status, 200)
            routes = {item["route"]: item for item in map_payload["routes"]}
            self.assertEqual(map_payload["items"][0]["seo"]["description"], "Primary page")
            self.assertEqual(map_payload["items"][0]["seo"]["og_title"], "OG imported")
            self.assertEqual(map_payload["items"][0]["seo"]["canonical"], "https://example.com/")
            self.assertEqual(routes["/missing"]["kind"], "sitemap")
            self.assertEqual(routes["/missing"]["status"], "unmatched")
            self.assertEqual(routes["/old"]["kind"], "redirect")
            self.assertIn("redirects to /new (302)", routes["/old"]["warnings"])

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
            self.assertIn("source_profile", context)
            self.assertTrue(context["source_profile"]["static_preview_supported"])

    def test_page_context_accepts_route_and_asset_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("index.html", '<title>Home</title><img src="assets/logo.png">')
                zip_file.writestr("assets/logo.png", b"\x89PNG\r\nphase1")
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")
            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "Context", "archive_base64": encoded})
            self.assertEqual(status, 201)
            site_id = imported["site"]["id"]
            status, map_payload = handle_action(data_root, {"action": "sitemap", "site_id": site_id})
            self.assertEqual(status, 200)
            route_id = map_payload["routes"][0]["id"]
            asset_id = map_payload["assets"][0]["id"]

            status, route_context = handle_action(data_root, {"action": "page_context", "site_id": site_id, "route_id": route_id})
            self.assertEqual(status, 200)
            self.assertEqual(route_context["active_view"], "page")
            self.assertEqual(route_context["route_id"], route_id)
            self.assertEqual(route_context["route"], "/")

            status, asset_context = handle_action(data_root, {"action": "page_context", "site_id": site_id, "asset_id": asset_id})
            self.assertEqual(status, 200)
            self.assertEqual(asset_context["active_view"], "asset")
            self.assertEqual(asset_context["asset_id"], asset_id)
            self.assertEqual(asset_context["asset_path"], "assets/logo.png")

    def test_reference_manifest_and_search_match_declared_entities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Acme"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            _edit_index(data_root, site_id)
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

    def test_reference_payloads_include_app_pages_and_deep_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("index.html", '<title>Home</title><img src="assets/logo.png">')
                zip_file.writestr("assets/logo.png", b"\x89PNG\r\nphase1")
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")
            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "Links", "archive_base64": encoded})
            self.assertEqual(status, 201)
            site_id = imported["site"]["id"]
            status, map_payload = handle_action(data_root, {"action": "sitemap", "site_id": site_id})
            self.assertEqual(status, 200)

            for entity_type, entity_id, route_prefix in (
                ("site", site_id, "sites/"),
                ("page", map_payload["items"][0]["id"], "pages/"),
                ("route", map_payload["routes"][0]["id"], "routes/"),
                ("asset", map_payload["assets"][0]["id"], "assets/"),
                ("revision", imported["revision"]["id"], "revisions/"),
            ):
                status, resolved = handle_action(data_root, {"action": "reference_resolve", "entity_type": entity_type, "id": entity_id})
                self.assertEqual(status, 200)
                self.assertTrue(resolved["item"]["app_page"].startswith(route_prefix))
                self.assertEqual(resolved["item"]["deep_link"], f"/app/website-studio/{resolved['item']['app_page']}")

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
        self.assertIn("map.routes || []", widget_source)
        self.assertIn("map.assets || []", widget_source)
        self.assertIn("route_id", widget_source)
        self.assertIn("asset_id", widget_source)
        self.assertIn("maverick.widget.data-changed", widget_source)

    def test_frontend_handles_route_and_asset_deep_links(self) -> None:
        app_source = (APP_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")

        self.assertIn("appPage.startsWith('routes/')", app_source)
        self.assertIn("appPage.startsWith('assets/')", app_source)
        self.assertIn("route_id", app_source)
        self.assertIn("asset_id", app_source)
        self.assertIn("maverick.app.selection-changed", app_source)

    def test_frontend_and_sidebar_do_not_select_archived_sites(self) -> None:
        app_source = (APP_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        widget_source = (APP_ROOT / "frontend" / "public" / "widgets" / "website-studio-sitemap-sidebar" / "index.html").read_text(encoding="utf-8")

        self.assertIn("availableSites = sitePayload.items.filter((site) => site.status !== 'archived')", app_source)
        self.assertIn("const selectableSites = sites.filter(item => item.status !== 'archived')", widget_source)
        self.assertNotIn("sitePayload.items[0]?.id", app_source)
        self.assertNotIn("|| sites[0]", widget_source)

    def test_frontend_resolves_storage_writer_dependency(self) -> None:
        api_source = (APP_ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
        app_source = (APP_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")

        self.assertIn("/api/apps/dependencies", api_source)
        self.assertIn("storage-writer", app_source)
        self.assertNotIn("/api/apps/storage/backend", api_source)

    def test_build_preview_does_not_emit_data_changed_event(self) -> None:
        self.assertEqual(app_events_for_action("build_preview"), [])

    def test_frontend_drop_zip_is_real_drop_target(self) -> None:
        app_source = (APP_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")

        self.assertIn("handleZipDrop", app_source)
        self.assertIn("onDrop={handleZipDrop}", app_source)
        self.assertIn("Drop a ZIP archive", app_source)

    def test_phase2_approval_publish_and_rollback_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Acme"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            initial_revision_id = created["site"]["active_revision_id"]
            _edit_index(data_root, site_id, marker="Published")

            status, publish_request = handle_action(data_root, {"action": "publish_request", "site_id": site_id, "requested_by": "agent"})
            self.assertEqual(status, 201)
            request_id = publish_request["publish_request"]["id"]
            self.assertTrue(publish_request["publish_request"]["build_id"])

            status, approval_payload = handle_action(
                data_root,
                {
                    "action": "approval_record",
                    "site_id": site_id,
                    "approval_action": "publish",
                    "target_id": request_id,
                    "approved_by": "owner@example.com",
                    "confirm": True,
                },
            )
            self.assertEqual(status, 201)

            status, published = handle_action(
                data_root,
                {
                    "action": "publish",
                    "site_id": site_id,
                    "publish_request_id": request_id,
                    "approval_id": approval_payload["approval"]["id"],
                },
            )
            self.assertEqual(status, 200)
            self.assertFalse(published["blocked"])
            self.assertEqual(published["status"], "published")
            self.assertEqual(published["publish_request"]["status"], "published")
            self.assertEqual(published["deployment"]["status"], "published")
            self.assertEqual(published["deployment"]["mode"], "internal_static_snapshot")

            status, diff = handle_action(data_root, {"action": "diff", "site_id": site_id})
            self.assertEqual(status, 200)
            self.assertEqual(diff["files"], [])

            status, rollback_approval = handle_action(
                data_root,
                {
                    "action": "approval_record",
                    "site_id": site_id,
                    "approval_action": "rollback",
                    "target_id": initial_revision_id,
                    "approved_by": "owner@example.com",
                    "confirm": True,
                },
            )
            self.assertEqual(status, 201)
            status, rolled_back = handle_action(
                data_root,
                {
                    "action": "rollback",
                    "site_id": site_id,
                    "revision_id": initial_revision_id,
                    "approval_id": rollback_approval["approval"]["id"],
                    "confirm": True,
                },
            )
            self.assertEqual(status, 200)
            self.assertFalse(rolled_back["blocked"])
            self.assertEqual(rolled_back["deployment"]["status"], "rolled_back")
            status, file_payload = handle_action(data_root, {"action": "read_file", "site_id": site_id, "path": "index.html"})
            self.assertEqual(status, 200)
            self.assertNotIn("Published", file_payload["file"]["content"])

            status, changes = handle_action(data_root, {"action": "list_changes", "site_id": site_id})
            self.assertEqual(status, 200)
            self.assertTrue(changes["approval_events"])
            self.assertTrue(changes["builds"])
            self.assertTrue(changes["deployments"])

    def test_phase2_approval_cannot_be_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Reuse"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            _edit_index(data_root, site_id)
            status, request_payload = handle_action(data_root, {"action": "publish_request", "site_id": site_id})
            self.assertEqual(status, 201)
            request_id = request_payload["publish_request"]["id"]
            status, approval_payload = handle_action(
                data_root,
                {
                    "action": "approval_record",
                    "site_id": site_id,
                    "approval_action": "publish",
                    "target_id": request_id,
                    "approved_by": "owner@example.com",
                    "confirm": True,
                },
            )
            self.assertEqual(status, 201)
            approval_id = approval_payload["approval"]["id"]
            status, first = handle_action(data_root, {"action": "publish", "site_id": site_id, "publish_request_id": request_id, "approval_id": approval_id})
            self.assertEqual(status, 200)
            status, second = handle_action(data_root, {"action": "publish", "site_id": site_id, "publish_request_id": request_id, "approval_id": approval_id})
            self.assertEqual(status, 400)
            self.assertIn("already published", second["detail"])

    def test_phase2_environments_are_site_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, first = handle_action(data_root, {"action": "site_create", "display_name": "One"})
            self.assertEqual(status, 201)
            status, second = handle_action(data_root, {"action": "site_create", "display_name": "Two"})
            self.assertEqual(status, 201)

            self.assertNotEqual(first["site"]["default_environment_id"], second["site"]["default_environment_id"])
            status, configured = handle_action(
                data_root,
                {
                    "action": "environment_configure",
                    "site_id": first["site"]["id"],
                    "kind": "production",
                    "name": "Production",
                    "base_url": "https://example.com",
                    "requires_approval": True,
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(configured["environment"]["kind"], "production")
            status, listed = handle_action(data_root, {"action": "environments_list", "site_id": first["site"]["id"]})
            self.assertEqual(status, 200)
            self.assertIn("production", {item["kind"] for item in listed["items"]})

    def test_phase2_git_connection_activation_requires_secret_grant_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, prepared = handle_action(data_root, {"action": "git_connection_prepare", "repository_url": "example-org/site-web"})
            self.assertEqual(status, 201)
            connection_id = prepared["connection"]["id"]

            status, blocked = handle_action(data_root, {"action": "git_connection_activate", "connection_id": connection_id, "grant_id": "grant_123"})
            self.assertEqual(status, 400)
            self.assertIn("confirm_no_raw_secret", blocked["detail"])

            status, activated = handle_action(
                data_root,
                {
                    "action": "git_connection_activate",
                    "connection_id": connection_id,
                    "grant_id": "grant_123",
                    "confirm_no_raw_secret": True,
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(activated["connection"]["status"], "grant_configured")

    def test_phase2_github_publish_opens_pull_request_with_vault_delivered_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, prepared = handle_action(data_root, {"action": "git_connection_prepare", "repository_url": "example-org/site-web"})
            self.assertEqual(status, 201)
            site_id = prepared["site"]["id"]
            connection_id = prepared["connection"]["id"]
            status, activated = handle_action(
                data_root,
                {
                    "action": "git_connection_activate",
                    "connection_id": connection_id,
                    "grant_id": "grant:default:website-studio:github-token:test",
                    "confirm_no_raw_secret": True,
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(activated["connection"]["status"], "grant_configured")
            _edit_index(data_root, site_id, marker="GitHub")
            status, request_payload = handle_action(data_root, {"action": "publish_request", "site_id": site_id})
            self.assertEqual(status, 201)
            request_id = request_payload["publish_request"]["id"]
            status, approval_payload = handle_action(
                data_root,
                {
                    "action": "approval_record",
                    "site_id": site_id,
                    "approval_action": "publish",
                    "target_id": request_id,
                    "approved_by": "owner@example.com",
                    "confirm": True,
                },
            )
            self.assertEqual(status, 201)

            transport = FakeGitHubTransport()
            status, published = handle_action(
                data_root,
                {
                    "action": "publish",
                    "site_id": site_id,
                    "publish_request_id": request_id,
                    "approval_id": approval_payload["approval"]["id"],
                    "_app_secrets": {"github-token": "test-github-token"},
                    "_github_transport": transport,
                },
            )

            self.assertEqual(status, 200)
            self.assertEqual(published["deployment"]["mode"], "github_pull_request")
            source_ref = published["deployment"]["source_ref"]
            self.assertEqual(source_ref["provider"], "github")
            self.assertEqual(source_ref["status"], "pull_request_open")
            self.assertEqual(source_ref["pull_request_url"], "https://github.com/example-org/site-web/pull/42")
            self.assertNotIn("test-github-token", json.dumps(published))
            auth_headers = [call[2]["headers"]["Authorization"] for call in transport.calls]
            self.assertTrue(all(header == "Bearer test-github-token" for header in auth_headers))

    def test_phase2_github_publish_missing_secret_blocks_before_approval_is_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, prepared = handle_action(data_root, {"action": "git_connection_prepare", "repository_url": "example-org/site-web"})
            self.assertEqual(status, 201)
            site_id = prepared["site"]["id"]
            status, _activated = handle_action(
                data_root,
                {
                    "action": "git_connection_activate",
                    "connection_id": prepared["connection"]["id"],
                    "grant_id": "grant:default:website-studio:github-token:test",
                    "confirm_no_raw_secret": True,
                },
            )
            self.assertEqual(status, 200)
            _edit_index(data_root, site_id, marker="Blocked")
            status, request_payload = handle_action(data_root, {"action": "publish_request", "site_id": site_id})
            self.assertEqual(status, 201)
            request_id = request_payload["publish_request"]["id"]
            status, approval_payload = handle_action(
                data_root,
                {
                    "action": "approval_record",
                    "site_id": site_id,
                    "approval_action": "publish",
                    "target_id": request_id,
                    "approved_by": "owner@example.com",
                    "confirm": True,
                },
            )
            self.assertEqual(status, 201)

            status, blocked = handle_action(
                data_root,
                {
                    "action": "publish",
                    "site_id": site_id,
                    "publish_request_id": request_id,
                    "approval_id": approval_payload["approval"]["id"],
                    "_app_secret_errors": [{"logical_name": "github-token"}],
                },
            )

            self.assertEqual(status, 403)
            self.assertTrue(blocked["blocked"])
            self.assertIn("Core Secrets did not deliver", blocked["detail"])
            status, approvals = handle_action(data_root, {"action": "approvals_list", "site_id": site_id})
            self.assertEqual(status, 200)
            approval = next(item for item in approvals["items"] if item["id"] == approval_payload["approval"]["id"])
            self.assertEqual(approval["status"], "approved")
            self.assertIsNone(approval["used_at"])

    def test_phase2_build_validation_records_static_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("index.html", "<title>Build</title>")
                zip_file.writestr("package.json", '{"scripts":{"build":"vite build"}}')
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")
            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "Build", "archive_base64": encoded})
            self.assertEqual(status, 201)

            status, build_payload = handle_action(data_root, {"action": "build_validate", "site_id": imported["site"]["id"]})
            self.assertEqual(status, 201)
            self.assertEqual(build_payload["build"]["status"], "passed")
            self.assertIn("not executed", " ".join(build_payload["build"]["warnings"]))


if __name__ == "__main__":
    unittest.main()
