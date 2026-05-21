from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from core.api.app_mounts import _read_backend_body, backend_entrypoint_timeout_seconds, serve_frontend
from core.api.http import HttpRequestError
from core.apps.contracts import build_app_contract, build_app_hook_timeouts, build_parsed_app_contract


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

    def test_backend_entrypoint_timeout_comes_from_app_contract(self) -> None:
        parsed = build_parsed_app_contract(
            app_id="speech",
            name="Speech",
            version="1.0.0",
            description="Speech provider.",
            publisher="maverick",
            contract=build_app_contract(hook_timeouts=build_app_hook_timeouts(backend_seconds=300)),
        )

        self.assertEqual(backend_entrypoint_timeout_seconds(parsed), 300)

    def test_non_json_backend_body_is_spooled_to_app_data_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = b"webm-audio"

            body, body_file = _read_backend_body(
                {
                    "CONTENT_TYPE": "audio/webm; codecs=opus",
                    "CONTENT_LENGTH": str(len(raw)),
                    "wsgi.input": BytesIO(raw),
                },
                data_root=str(root),
            )

            self.assertEqual(body, {})
            self.assertIsNotNone(body_file)
            assert body_file is not None
            self.assertEqual(body_file["content_type"], "audio/webm")
            self.assertEqual(body_file["size_bytes"], len(raw))
            body_path = Path(str(body_file["path"]))
            self.assertEqual(body_path.read_bytes(), raw)
            self.assertEqual(body_path.parent, root / "run" / "http-body")

    def test_speech_binary_backend_body_uses_inline_audio_limit_before_spooling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = b"x" * 700_001

            with self.assertRaises(HttpRequestError) as raised:
                _read_backend_body(
                    {
                        "CONTENT_TYPE": "audio/webm",
                        "CONTENT_LENGTH": str(len(raw)),
                        "wsgi.input": BytesIO(raw),
                    },
                    data_root=str(root),
                    app_id="speech",
                )

            self.assertEqual(raised.exception.error, "request_body_too_large")
            self.assertFalse((root / "run" / "http-body").exists())


def _serve(root: Path, subpath: str, *, cross_origin: bool = False) -> tuple[str, dict[str, str]]:
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = dict(headers)

    serve_frontend(start_response, frontend_root=root, subpath=subpath, cross_origin=cross_origin)
    return str(captured["status"]), captured["headers"]  # type: ignore[return-value]


if __name__ == "__main__":
    unittest.main()
