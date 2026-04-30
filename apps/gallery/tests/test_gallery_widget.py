"""Tests for the Gallery file preview widget mount."""

from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state


REPO_ROOT = Path(__file__).resolve().parents[3]


class GalleryWidgetTestCase(unittest.TestCase):
    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        shutil.copy2(REPO_ROOT / "core" / "__init__.py", repo_root / "core" / "__init__.py")
        shutil.copytree(REPO_ROOT / "core" / "app_sdk", repo_root / "core" / "app_sdk")
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

    def test_platform_exposes_gallery_file_preview_widget(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        registry_status, registry_payload, _registry_headers = self.invoke(
            app,
            path="/api/apps/widgets",
            query_string="host=chat&content_kind=gallery.file.preview",
            cookie=cookie,
        )
        mount_status, mount_payload, mount_headers = self.invoke(
            app,
            path="/api/apps/widgets/gallery/file-preview/frontend/",
            cookie=cookie,
        )

        self.assertEqual(registry_status, 200)
        self.assertEqual(registry_payload["items"][0]["owner_app_id"], "gallery")
        self.assertEqual(registry_payload["items"][0]["widget_id"], "file-preview")
        self.assertEqual(registry_payload["items"][0]["frontend_mount"], "/api/apps/widgets/gallery/file-preview/frontend/")
        self.assertEqual(mount_status, 200)
        self.assertIn("text/html", mount_headers["Content-Type"])
        self.assertIn(b"Gallery file preview", mount_payload)


if __name__ == "__main__":
    unittest.main()
