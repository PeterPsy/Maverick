from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.api.app_mounts import serve_frontend


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


def _serve(root: Path, subpath: str, *, cross_origin: bool = False) -> tuple[str, dict[str, str]]:
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = dict(headers)

    serve_frontend(start_response, frontend_root=root, subpath=subpath, cross_origin=cross_origin)
    return str(captured["status"]), captured["headers"]  # type: ignore[return-value]


if __name__ == "__main__":
    unittest.main()
