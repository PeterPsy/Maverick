"""Phase 1-3A Website Studio acceptance smoke tests."""

from __future__ import annotations

import base64
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

APP_ROOT = Path(__file__).resolve().parents[1]
MAVERICK_ROOT = next(parent for parent in APP_ROOT.parents if (parent / "core").is_dir())
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(APP_ROOT / "backend"))

from backend.service import handle_action
from preview_runtime import _shutdown_php_preview_servers


def _approval_actor(user_id: str = "user:owner", workspace_role: str = "owner") -> dict[str, object]:
    return {
        "user_id": user_id,
        "workspace_role": workspace_role,
        "platform_role": "",
        "effective_mode": "sandbox",
    }


def _zip_base64(entries: dict[str, str | bytes]) -> str:
    archive = BytesIO()
    with ZipFile(archive, "w") as zip_file:
        for path, content in entries.items():
            if isinstance(content, bytes):
                zip_file.writestr(path, content)
            else:
                zip_file.writestr(path, content.encode("utf-8"))
    return base64.b64encode(archive.getvalue()).decode("ascii")


def _call(data_root: Path, payload: dict[str, object], expected_status: int = 200) -> dict[str, object]:
    status, result = handle_action(data_root, payload)
    if status != expected_status:
        raise AssertionError(f"{payload.get('action')} returned {status}: {result}")
    return result


def _write_node_fixture(root: Path) -> None:
    vendor = root / "vendor" / "fake-vite"
    (vendor / "bin").mkdir(parents=True)
    (vendor / "package.json").write_text(
        json.dumps({"name": "vite", "version": "0.0.0-smoke", "bin": {"vite": "bin/vite.js"}}),
        encoding="utf-8",
    )
    (vendor / "bin" / "vite.js").write_text(
        "\n".join(
            [
                "#!/usr/bin/env node",
                "const fs = require('fs');",
                "fs.mkdirSync('dist', { recursive: true });",
                "fs.writeFileSync('dist/index.html', '<!doctype html><html><head><title>Node Smoke</title></head><body><main>Node Runtime Smoke</main><a href=\"/about\">About</a></body></html>');",
                "fs.writeFileSync('dist/about.html', '<!doctype html><html><head><title>About Smoke</title></head><body><main>About Runtime Smoke</main></body></html>');",
            ]
        ),
        encoding="utf-8",
    )
    (root / "package.json").write_text(
        json.dumps({"scripts": {"build": "vite build"}, "dependencies": {"vite": "file:vendor/fake-vite"}}),
        encoding="utf-8",
    )
    (root / "src").mkdir()
    (root / "src" / "entry.js").write_text("console.log('smoke');\n", encoding="utf-8")
    subprocess.run(
        ["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _zip_directory_base64(root: Path) -> str:
    archive = BytesIO()
    with ZipFile(archive, "w") as zip_file:
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            zip_file.write(path, path.relative_to(root).as_posix())
    return base64.b64encode(archive.getvalue()).decode("ascii")


class WebsiteStudioPhaseAcceptanceSmokeTest(unittest.TestCase):
    def tearDown(self) -> None:
        _shutdown_php_preview_servers()

    def test_static_zip_import_preview_publish_and_rollback_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            archive_base64 = _zip_base64(
                {
                    "index.html": "<!doctype html><html><head><title>Static Smoke</title><link rel=\"stylesheet\" href=\"style.css\"></head><body><main>Static Smoke</main></body></html>",
                    "style.css": "body { color: #111; }",
                }
            )
            source_ref = {
                "provider": "storage",
                "workspace_relative_path": "storage/generated/website-studio-static-smoke.zip",
                "file_id": "file_smoke_static",
            }

            imported = _call(
                data_root,
                {
                    "action": "import_zip",
                    "display_name": "Static Smoke",
                    "archive_base64": archive_base64,
                    "source_artifact_ref": source_ref,
                },
                expected_status=201,
            )
            site_id = str(imported["site"]["id"])
            initial_revision_id = str(imported["revision"]["id"])
            self.assertEqual(imported["site"]["source_artifact_ref"]["workspace_relative_path"], source_ref["workspace_relative_path"])
            self.assertEqual(imported["site"]["source_artifact_ref"]["file_id"], source_ref["file_id"])
            self.assertEqual(imported["import"]["source_profile"]["preview_runtime_kind"], "static_export")

            preview = _call(data_root, {"action": "build_preview", "site_id": site_id, "route": "/"})
            self.assertEqual(preview["runtime_status"], "ready")
            document = _call(data_root, {"action": "preview_document", "preview_id": preview["preview_id"]})
            self.assertIn("Static Smoke", document["html"])
            report = _call(data_root, {"action": "preview_report", "preview_id": preview["preview_id"]}, expected_status=201)
            self.assertEqual(report["report"]["runtime_status"], "ready")

            read_payload = _call(data_root, {"action": "read_file", "site_id": site_id, "path": "index.html"})
            edited_html = read_payload["file"]["content"].replace("Static Smoke</main>", "Static Smoke Published</main>")
            _call(
                data_root,
                {
                    "action": "write_file",
                    "site_id": site_id,
                    "path": "index.html",
                    "content": edited_html,
                    "expected_hash": read_payload["file"]["hash"],
                },
            )
            diff = _call(data_root, {"action": "diff", "site_id": site_id})
            self.assertEqual([item["path"] for item in diff["files"]], ["index.html"])

            request = _call(data_root, {"action": "publish_request", "site_id": site_id}, expected_status=201)
            approval = _call(
                data_root,
                {
                    "action": "approval_record",
                    "site_id": site_id,
                    "approval_action": "publish",
                    "target_id": request["publish_request"]["id"],
                    "approved_by": "user:owner",
                    "_app_actor": _approval_actor(),
                    "confirm": True,
                },
                expected_status=201,
            )
            published = _call(
                data_root,
                {
                    "action": "publish",
                    "site_id": site_id,
                    "publish_request_id": request["publish_request"]["id"],
                    "approval_id": approval["approval"]["id"],
                },
            )
            self.assertEqual(published["deployment"]["mode"], "maverick_managed_static")
            self.assertEqual(published["deployment"]["source_ref"]["platform_binding_status"], "pending_generic_surface")

            rollback_approval = _call(
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
                expected_status=201,
            )
            rolled_back = _call(
                data_root,
                {
                    "action": "rollback",
                    "site_id": site_id,
                    "revision_id": initial_revision_id,
                    "approval_id": rollback_approval["approval"]["id"],
                    "confirm": True,
                },
            )
            self.assertEqual(rolled_back["deployment"]["status"], "rolled_back")
            restored = _call(data_root, {"action": "read_file", "site_id": site_id, "path": "index.html"})
            self.assertNotIn("Published", restored["file"]["content"])

    @unittest.skipUnless(shutil.which("npm"), "npm executable is required for Node runtime smoke")
    def test_node_build_uses_real_npm_ci_and_runtime_artifact_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            fixture_root = Path(tmp) / "node-site"
            fixture_root.mkdir()
            _write_node_fixture(fixture_root)
            imported = _call(
                data_root,
                {
                    "action": "import_zip",
                    "display_name": "Node Smoke",
                    "archive_base64": _zip_directory_base64(fixture_root),
                },
                expected_status=201,
            )
            site_id = str(imported["site"]["id"])
            self.assertEqual(imported["import"]["source_profile"]["preview_runtime_kind"], "node_build")

            build = _call(data_root, {"action": "build_validate", "site_id": site_id}, expected_status=201)
            self.assertEqual(build["build"]["status"], "passed")
            self.assertEqual(build["build"]["runtime_kind"], "node_build")
            self.assertIn("npm ci --ignore-scripts --no-audit --no-fund", build["build"]["logs_summary"])
            artifact_root = data_root / build["build"]["artifact_ref"]["runtime_root"]
            self.assertTrue((artifact_root / "dist" / "index.html").exists())
            self.assertFalse((artifact_root / ".website-studio-runtime-env").exists())

            preview = _call(data_root, {"action": "build_preview", "site_id": site_id, "route": "/"})
            self.assertEqual(preview["runtime_status"], "ready")
            self.assertEqual(preview["runtime_kind"], "node_build")
            self.assertIn("Node Runtime Smoke", preview["html"])
            sitemap = _call(data_root, {"action": "sitemap", "site_id": site_id})
            routes = {item["route"] for item in sitemap["routes"]}
            self.assertIn("/", routes)
            self.assertIn("/about", routes)

    @unittest.skipUnless(shutil.which("php"), "php executable is required for PHP runtime smoke")
    def test_php_runtime_smoke_when_host_php_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            imported = _call(
                data_root,
                {
                    "action": "import_zip",
                    "display_name": "PHP Smoke",
                    "archive_base64": _zip_base64({"index.php": "<?php echo '<!doctype html><title>PHP Smoke</title><main>PHP Runtime Smoke</main>';"}),
                },
                expected_status=201,
            )
            site_id = str(imported["site"]["id"])
            build = _call(data_root, {"action": "build_validate", "site_id": site_id}, expected_status=201)
            self.assertEqual(build["build"]["status"], "passed")
            preview = _call(data_root, {"action": "build_preview", "site_id": site_id, "route": "/"})
            self.assertEqual(preview["runtime_status"], "ready")
            self.assertEqual(preview["runtime_kind"], "php")
            self.assertIn("PHP Runtime Smoke", preview["html"])


class WebsiteStudioExternalAcceptanceSmokeTest(unittest.TestCase):
    def test_optional_live_github_pull_request_smoke(self) -> None:
        repo = os.environ.get("WEBSITE_STUDIO_LIVE_GITHUB_REPO", "").strip()
        token = os.environ.get("WEBSITE_STUDIO_LIVE_GITHUB_TOKEN", "").strip()
        confirm = os.environ.get("WEBSITE_STUDIO_LIVE_GITHUB_CONFIRM", "").strip()
        if not repo or not token or confirm != "create_pr":
            self.skipTest("set WEBSITE_STUDIO_LIVE_GITHUB_REPO, WEBSITE_STUDIO_LIVE_GITHUB_TOKEN, and WEBSITE_STUDIO_LIVE_GITHUB_CONFIRM=create_pr")
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            prepared = _call(data_root, {"action": "git_connection_prepare", "repository_url": repo}, expected_status=201)
            site_id = str(prepared["site"]["id"])
            _call(
                data_root,
                {
                    "action": "git_connection_activate",
                    "connection_id": prepared["connection"]["id"],
                    "grant_id": f"grant:default:website-studio:github-token:{site_id}",
                    "confirm_no_raw_secret": True,
                },
            )
            read_payload = _call(data_root, {"action": "read_file", "site_id": site_id, "path": "index.html"})
            _call(
                data_root,
                {
                    "action": "write_file",
                    "site_id": site_id,
                    "path": "index.html",
                    "content": read_payload["file"]["content"].replace("</main>", "<p>Live GitHub smoke</p></main>"),
                    "expected_hash": read_payload["file"]["hash"],
                },
            )
            request = _call(data_root, {"action": "publish_request", "site_id": site_id}, expected_status=201)
            approval = _call(
                data_root,
                {
                    "action": "approval_record",
                    "site_id": site_id,
                    "approval_action": "publish",
                    "target_id": request["publish_request"]["id"],
                    "approved_by": "user:owner",
                    "_app_actor": _approval_actor(),
                    "confirm": True,
                },
                expected_status=201,
            )
            published = _call(
                data_root,
                {
                    "action": "publish",
                    "site_id": site_id,
                    "publish_request_id": request["publish_request"]["id"],
                    "approval_id": approval["approval"]["id"],
                    "_app_secrets": {"github-token": token},
                },
            )
            self.assertEqual(published["deployment"]["mode"], "github_pull_request")
            self.assertNotIn(token, json.dumps(published))
            self.assertTrue(published["deployment"]["source_ref"]["pull_request_url"])

    def test_optional_storage_cli_zip_round_trip_smoke(self) -> None:
        if os.environ.get("WEBSITE_STUDIO_STORAGE_CLI_SMOKE") != "1":
            self.skipTest("set WEBSITE_STUDIO_STORAGE_CLI_SMOKE=1 to write a generated Storage smoke ZIP")
        archive_base64 = _zip_base64({"index.html": "<!doctype html><title>Storage Smoke</title><main>Storage ZIP Smoke</main>"})
        rel_path = f"storage/generated/website-studio-smoke-{os.getpid()}.zip"
        written = _run_maverick_json(
            [
                "maverick",
                "app",
                "storage",
                "mcp",
                "call",
                "storage_write_file",
                "--workspace-relative-path",
                rel_path,
                "--mode",
                "create",
                "--content-base64",
                archive_base64,
                "--json",
            ]
        )
        read_back = _run_maverick_json(
            [
                "maverick",
                "app",
                "storage",
                "mcp",
                "call",
                "storage_read_file",
                "--workspace-relative-path",
                rel_path,
                "--max-bytes",
                "2000000",
                "--json",
            ]
        )
        self.assertEqual(read_back["content_base64"], archive_base64)
        with tempfile.TemporaryDirectory() as tmp:
            imported = _call(
                Path(tmp),
                {
                    "action": "import_zip",
                    "display_name": "Storage CLI Smoke",
                    "archive_base64": read_back["content_base64"],
                    "source_artifact_ref": written["file"],
                },
                expected_status=201,
            )
            self.assertEqual(imported["site"]["source_artifact_ref"]["workspace_relative_path"], rel_path)


def _run_maverick_json(args: list[str]) -> dict[str, object]:
    result = subprocess.run(args, cwd=MAVERICK_ROOT / "workspaces" / "default", check=True, capture_output=True, text=True, timeout=60)
    return json.loads(result.stdout)


if __name__ == "__main__":
    unittest.main()
