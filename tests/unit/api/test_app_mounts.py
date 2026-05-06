from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from core.api.app_mounts import DEFAULT_APP_BACKEND_TIMEOUT_SECONDS, app_backend_timeout_seconds, serve_frontend


class AppMountsTestCase(unittest.TestCase):
    def test_frontend_html_documents_are_not_cached(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text("<!doctype html><div id=\"root\"></div>", encoding="utf-8")

            status, headers = _serve(root, "/")

        self.assertEqual(status, "200 OK")
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_cross_origin_static_assets_are_cacheable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset_dir = root / "assets"
            asset_dir.mkdir()
            (asset_dir / "app-abc123.js").write_text("console.log('app')", encoding="utf-8")

            status, headers = _serve(root, "/assets/app-abc123.js", cross_origin=True)

        self.assertEqual(status, "200 OK")
        self.assertEqual(headers["Cache-Control"], "public, max-age=31536000, immutable")
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")
        self.assertEqual(headers["Cross-Origin-Resource-Policy"], "cross-origin")

    def test_app_backend_timeout_default_allows_long_running_app_operations(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(app_backend_timeout_seconds(), DEFAULT_APP_BACKEND_TIMEOUT_SECONDS)
            self.assertGreaterEqual(app_backend_timeout_seconds(), 300)

    def test_app_backend_timeout_env_override_has_30_second_floor(self) -> None:
        with patch.dict("os.environ", {"MAVERICK_APP_BACKEND_TIMEOUT_SECONDS": "5"}):
            self.assertEqual(app_backend_timeout_seconds(), 30)
        with patch.dict("os.environ", {"MAVERICK_APP_BACKEND_TIMEOUT_SECONDS": "900"}):
            self.assertEqual(app_backend_timeout_seconds(), 900)


def _serve(root: Path, subpath: str, *, cross_origin: bool = False) -> tuple[str, dict[str, str]]:
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = dict(headers)

    serve_frontend(start_response, frontend_root=root, subpath=subpath, cross_origin=cross_origin)
    return str(captured["status"]), captured["headers"]  # type: ignore[return-value]


if __name__ == "__main__":
    unittest.main()
