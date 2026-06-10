from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.contracts import build_app_contract, build_parsed_app_contract, write_app_contract_file
from core.apps.service import install_store_app, register_app_source_from_contract


class AppFileGatewayIntegrationTests(unittest.TestCase):
    def test_public_file_gateway_is_served_anonymously_through_platform_host(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo_root = self._repo_root(temp)
            state = bootstrap_platform_state(start_path=repo_root)
            binding = self._install_minimal_app(repo_root, state)
            media_path = Path(binding.data_root) / "sites" / "site_1" / "source" / "assets" / "hero.webp"
            media_path.parent.mkdir(parents=True)
            media_path.write_bytes(b"0123456789")
            token = "gw_test_public_capability_123456"
            manifest_root = Path(binding.data_root) / "run" / "file-gateway"
            manifest_root.mkdir(parents=True)
            (manifest_root / f"{token}.json").write_text(
                json.dumps(
                    {
                        "schema": "maverick.app.file_gateway.v1",
                        "app_id": "website-studio",
                        "access": "public_capability",
                        "expires_at": (datetime.now(tz=UTC) + timedelta(minutes=15)).isoformat(),
                        "allowed_paths": [str(media_path.resolve())],
                        "file_response": {
                            "path": str(media_path.resolve()),
                            "content_type": "image/webp",
                            "etag": "hero-etag",
                            "headers": {"Access-Control-Allow-Origin": "*"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            app = PlatformHost(state, start_path=repo_root)

            status, body, headers = self._invoke_raw(
                app,
                path=f"/api/apps/website-studio/backend/file/{token}",
                extra_environ={"HTTP_RANGE": "bytes=2-5"},
            )

        self.assertEqual(status, 206)
        self.assertEqual(headers["Content-Range"], "bytes 2-5/10")
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")
        self.assertEqual(headers["ETag"], '"hero-etag"')
        self.assertEqual(body, b"2345")

    def test_public_file_gateway_serves_css_and_fonts_inline_through_platform_host(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo_root = self._repo_root(temp)
            state = bootstrap_platform_state(start_path=repo_root)
            binding = self._install_minimal_app(repo_root, state)
            app = PlatformHost(state, start_path=repo_root)
            data_root = Path(binding.data_root)
            cases = [
                ("gw_test_public_css_inline_1234", "assets/site.css", "body { color: #111; }", "text/css; charset=utf-8"),
                ("gw_test_public_font_inline_123", "assets/fonts/site.woff2", "font", "font/woff2"),
            ]

            for token, rel_path, content, content_type in cases:
                with self.subTest(content_type=content_type):
                    media_path = data_root / "sites" / "site_1" / "source" / rel_path
                    media_path.parent.mkdir(parents=True, exist_ok=True)
                    media_path.write_bytes(content.encode("utf-8"))
                    self._write_gateway_manifest(
                        data_root=data_root,
                        token=token,
                        media_path=media_path,
                        content_type=content_type,
                    )

                    status, body, headers = self._invoke_raw(
                        app,
                        path=f"/api/apps/website-studio/backend/file/{token}",
                    )

                    self.assertEqual(status, 200)
                    self.assertEqual(headers["Content-Type"], content_type)
                    self.assertEqual(headers["Content-Disposition"], f'inline; filename="{media_path.name}"')
                    self.assertEqual(headers["Access-Control-Allow-Origin"], "*")
                    self.assertEqual(body, content.encode("utf-8"))

    def _repo_root(self, temp_dir: str) -> Path:
        repo_root = Path(temp_dir) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def _install_minimal_app(self, repo_root: Path, state):
        app_root = repo_root / "apps" / "website-studio"
        app_root.mkdir(parents=True)
        parsed = build_parsed_app_contract(
            app_id="website-studio",
            name="Website Studio",
            version="1.0.0",
            description="Preview gateway test app.",
            publisher="maverick",
            contract=build_app_contract(),
        )
        write_app_contract_file(app_root, parsed)
        source = register_app_source_from_contract(
            state.app_store,
            source_kind="platform",
            source_path=str(app_root),
        )
        return install_store_app(
            state.app_store,
            source_id=source.source_id,
            workspace_id="default",
            start_path=repo_root,
            observability_store=state.observability_store,
        )

    def _write_gateway_manifest(self, *, data_root: Path, token: str, media_path: Path, content_type: str) -> None:
        manifest_root = data_root / "run" / "file-gateway"
        manifest_root.mkdir(parents=True, exist_ok=True)
        (manifest_root / f"{token}.json").write_text(
            json.dumps(
                {
                    "schema": "maverick.app.file_gateway.v1",
                    "app_id": "website-studio",
                    "access": "public_capability",
                    "expires_at": (datetime.now(tz=UTC) + timedelta(minutes=15)).isoformat(),
                    "allowed_paths": [str(media_path.resolve())],
                    "file_response": {
                        "path": str(media_path.resolve()),
                        "content_type": content_type,
                        "headers": {"Access-Control-Allow-Origin": "*"},
                    },
                }
            ),
            encoding="utf-8",
        )

    def _invoke_raw(
        self,
        app: PlatformHost,
        *,
        path: str,
        method: str = "GET",
        extra_environ: dict[str, str] | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": "0",
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": "",
            "wsgi.input": BytesIO(b""),
        }
        environ.update(extra_environ or {})

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        body = b"".join(app(environ, start_response))
        return int(headers["__status__"].split()[0]), body, headers


if __name__ == "__main__":
    unittest.main()
