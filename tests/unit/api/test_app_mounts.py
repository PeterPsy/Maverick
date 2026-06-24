from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from core.api.app_mounts import _apply_app_secret_writes, _backend_request_headers, _backend_secret_request_body, _read_backend_body, _resolve_app_secret_payload, _serve_app_file_gateway_manifest, _serve_app_file_response, backend_entrypoint_timeout_seconds, serve_frontend
from core.api.http import HttpRequestError
from core.apps.contracts import build_app_contract, build_app_hook_timeouts, build_parsed_app_contract
from core.observability.store import ObservabilityCollections, ObservabilityDocumentStore
from core.secrets.app_delivery import app_secret_target
from core.secrets.errors import SecretPolicyError
from core.secrets.service import bind_app_secret, build_secret_ref, create_platform_secret, grant_app_secret_use
from core.secrets.store import SecretCollections, SecretDocumentStore
from tests.support.collections import FakeCollection


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

            with self.assertRaises(HttpRequestError) as raised:
                _read_backend_body(
                    {
                        "CONTENT_TYPE": "audio/webm",
                        "CONTENT_LENGTH": str(20_000_001),
                        "wsgi.input": BytesIO(b""),
                    },
                    data_root=str(root),
                    app_id="speech",
                )

            self.assertEqual(raised.exception.error, "request_body_too_large")
            self.assertFalse((root / "run" / "http-body").exists())

    def test_speech_binary_backend_body_allows_recordings_over_previous_700kb_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = b"x" * 700_001

            body, body_file = _read_backend_body(
                {
                    "CONTENT_TYPE": "audio/webm",
                    "CONTENT_LENGTH": str(len(raw)),
                    "wsgi.input": BytesIO(raw),
                },
                data_root=str(root),
                app_id="speech",
            )

            self.assertEqual(body, {})
            self.assertIsNotNone(body_file)
            assert body_file is not None
            self.assertEqual(body_file["size_bytes"], len(raw))
            self.assertEqual(Path(str(body_file["path"])).read_bytes(), raw)

    def test_app_file_response_serves_single_byte_range(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_path = root / "clip.mp4"
            media_path.write_bytes(b"0123456789")

            status, headers, body = _serve_file_response(
                root=root,
                file_response={"path": str(media_path), "content_type": "video/mp4", "file_name": "clip.mp4", "etag": "clip-etag"},
                environ={"REQUEST_METHOD": "GET", "HTTP_RANGE": "bytes=2-5"},
            )

        self.assertEqual(status, "206 Partial Content")
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        self.assertEqual(headers["Content-Range"], "bytes 2-5/10")
        self.assertEqual(headers["Content-Length"], "4")
        self.assertEqual(headers["ETag"], "\"clip-etag\"")
        self.assertEqual(headers["Content-Disposition"], 'inline; filename="clip.mp4"')
        self.assertEqual(body, b"2345")

    def test_app_file_response_allows_safe_extra_headers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_path = root / "font.woff2"
            media_path.write_bytes(b"font")

            status, headers, body = _serve_file_response(
                root=root,
                file_response={
                    "path": str(media_path),
                    "content_type": "font/woff2",
                    "headers": {
                        "Access-Control-Allow-Origin": "*",
                        "Cross-Origin-Resource-Policy": "cross-origin",
                        "Set-Cookie": "blocked=true",
                        "X-Unsafe": "blocked",
                    },
                },
                environ={"REQUEST_METHOD": "GET"},
            )

        self.assertEqual(status, "200 OK")
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")
        self.assertEqual(headers["Cross-Origin-Resource-Policy"], "cross-origin")
        self.assertNotIn("Set-Cookie", headers)
        self.assertNotIn("X-Unsafe", headers)
        self.assertEqual(headers["Content-Disposition"], 'inline; filename="font.woff2"')
        self.assertEqual(body, b"font")

    def test_app_file_response_serves_css_inline_for_subresources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            css_path = root / "site.css"
            css_path.write_text("body { color: black; }", encoding="utf-8")

            status, headers, body = _serve_file_response(
                root=root,
                file_response={"path": str(css_path), "content_type": "text/css; charset=utf-8"},
                environ={"REQUEST_METHOD": "GET"},
            )

        self.assertEqual(status, "200 OK")
        self.assertEqual(headers["Content-Disposition"], 'inline; filename="site.css"')
        self.assertEqual(body, b"body { color: black; }")

    def test_app_file_response_deletes_ephemeral_run_file_after_send(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_path = root / "run" / "folder_downloads" / "folder.zip"
            media_path.parent.mkdir(parents=True)
            media_path.write_bytes(b"zip")

            status, headers, body = _serve_file_response(
                root=root,
                file_response={
                    "path": str(media_path),
                    "content_type": "application/zip",
                    "file_name": "folder.zip",
                    "download": True,
                    "delete_after_send": True,
                },
                environ={"REQUEST_METHOD": "GET"},
            )

            self.assertEqual(status, "200 OK")
            self.assertEqual(headers["Content-Disposition"], 'attachment; filename="folder.zip"')
            self.assertEqual(body, b"zip")
            self.assertFalse(media_path.exists())

    def test_app_file_response_deletes_ephemeral_run_file_after_invalid_range(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_path = root / "run" / "folder_downloads" / "folder.zip"
            media_path.parent.mkdir(parents=True)
            media_path.write_bytes(b"zip")

            status, headers, body = _serve_file_response(
                root=root,
                file_response={
                    "path": str(media_path),
                    "content_type": "application/zip",
                    "file_name": "folder.zip",
                    "download": True,
                    "delete_after_send": True,
                },
                environ={"REQUEST_METHOD": "GET", "HTTP_RANGE": "bytes=999-1000"},
            )

            self.assertEqual(status, "416 Range Not Satisfiable")
            self.assertEqual(headers["Content-Range"], "bytes */3")
            self.assertEqual(body, b"")
            self.assertFalse(media_path.exists())

    def test_app_file_response_ignores_delete_after_send_outside_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_path = root / "storage-file.bin"
            media_path.write_bytes(b"file")

            status, _headers, body = _serve_file_response(
                root=root,
                file_response={
                    "path": str(media_path),
                    "content_type": "application/octet-stream",
                    "delete_after_send": True,
                },
                environ={"REQUEST_METHOD": "GET"},
            )

            self.assertEqual(status, "200 OK")
            self.assertEqual(body, b"file")
            self.assertTrue(media_path.exists())

    def test_app_file_response_handles_invalid_range_and_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_path = root / "clip.mp4"
            media_path.write_bytes(b"0123456789")

            invalid_status, invalid_headers, invalid_body = _serve_file_response(
                root=root,
                file_response={"path": str(media_path), "content_type": "video/mp4"},
                environ={"REQUEST_METHOD": "GET", "HTTP_RANGE": "bytes=20-30"},
            )
            head_status, head_headers, head_body = _serve_file_response(
                root=root,
                file_response={"path": str(media_path), "content_type": "video/mp4"},
                environ={"REQUEST_METHOD": "HEAD"},
            )

        self.assertEqual(invalid_status, "416 Range Not Satisfiable")
        self.assertEqual(invalid_headers["Content-Range"], "bytes */10")
        self.assertEqual(invalid_body, b"")
        self.assertEqual(head_status, "200 OK")
        self.assertEqual(head_headers["Content-Length"], "10")
        self.assertEqual(head_body, b"")

    def test_app_file_response_forces_attachment_for_scriptable_content_types(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            html_path = root / "report.html"
            svg_path = root / "logo.svg"
            html_path.write_text("<script>alert(1)</script>", encoding="utf-8")
            svg_path.write_text("<svg><script>alert(1)</script></svg>", encoding="utf-8")

            html_status, html_headers, _html_body = _serve_file_response(
                root=root,
                file_response={"path": str(html_path), "content_type": "text/html", "file_name": "report.html"},
                environ={"REQUEST_METHOD": "GET"},
            )
            svg_status, svg_headers, _svg_body = _serve_file_response(
                root=root,
                file_response={"path": str(svg_path), "content_type": "image/svg+xml", "file_name": "logo.svg"},
                environ={"REQUEST_METHOD": "GET"},
            )

        self.assertEqual(html_status, "200 OK")
        self.assertEqual(svg_status, "200 OK")
        self.assertEqual(html_headers["Content-Disposition"], 'attachment; filename="report.html"')
        self.assertEqual(svg_headers["Content-Disposition"], 'attachment; filename="logo.svg"')
        self.assertEqual(html_headers["X-Content-Type-Options"], "nosniff")

    def test_app_file_response_serves_app_materialized_range_without_reslicing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            range_path = root / "range.bin"
            range_path.write_bytes(b"2345")

            status, headers, body = _serve_file_response(
                root=root,
                file_response={
                    "path": str(range_path),
                    "content_type": "video/mp4",
                    "file_name": "clip.mp4",
                    "etag": "range-etag",
                    "served_range": {"start": 2, "end": 5, "size": 10},
                },
                environ={"REQUEST_METHOD": "GET", "HTTP_RANGE": "bytes=2-5"},
            )

        self.assertEqual(status, "206 Partial Content")
        self.assertEqual(headers["Content-Range"], "bytes 2-5/10")
        self.assertEqual(headers["Content-Length"], "4")
        self.assertEqual(body, b"2345")

    def test_app_file_response_rejects_paths_outside_allowed_roots(self) -> None:
        with tempfile.TemporaryDirectory() as allowed, tempfile.TemporaryDirectory() as outside:
            outside_path = Path(outside) / "secret.bin"
            outside_path.write_bytes(b"nope")

            status, _headers, body = _serve_file_response(
                root=Path(allowed),
                file_response={"path": str(outside_path)},
                environ={"REQUEST_METHOD": "GET"},
            )

        self.assertEqual(status, "403 Forbidden")
        self.assertIn(b"file_response_forbidden", body)

    def test_app_file_gateway_manifest_serves_approved_file_without_backend(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_path = root / "sites" / "site_1" / "source" / "assets" / "hero.mp4"
            media_path.parent.mkdir(parents=True)
            media_path.write_bytes(b"0123456789")
            token = "gateway_token_123456789012"
            manifest_root = root / "run" / "file-gateway"
            manifest_root.mkdir(parents=True)
            (manifest_root / f"{token}.json").write_text(
                json.dumps(
                    {
                        "schema": "maverick.app.file_gateway.v1",
                        "app_id": "website-studio",
                        "file_response": {
                            "path": str(media_path),
                            "content_type": "video/mp4",
                            "etag": "hero-etag",
                            "headers": {"Access-Control-Allow-Origin": "*"},
                        },
                    }
                ),
                encoding="utf-8",
            )

            status, headers, body = _serve_file_gateway_manifest(
                root=root,
                manifest_root=manifest_root,
                token=token,
                app_id="website-studio",
                environ={"REQUEST_METHOD": "GET", "HTTP_RANGE": "bytes=4-8"},
            )

        self.assertEqual(status, "206 Partial Content")
        self.assertEqual(headers["Content-Range"], "bytes 4-8/10")
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")
        self.assertEqual(headers["ETag"], "\"hero-etag\"")
        self.assertEqual(body, b"45678")

    def test_public_app_file_gateway_manifest_requires_exact_allowed_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allowed_path = root / "sites" / "site_1" / "source" / "assets" / "hero.mp4"
            other_path = root / "sites" / "site_1" / "source" / "assets" / "other.mp4"
            allowed_path.parent.mkdir(parents=True)
            allowed_path.write_bytes(b"hero")
            other_path.write_bytes(b"other")
            token = "public_gateway_token_12345"
            manifest_root = root / "run" / "file-gateway"
            manifest_root.mkdir(parents=True)
            (manifest_root / f"{token}.json").write_text(
                json.dumps(
                    {
                        "schema": "maverick.app.file_gateway.v1",
                        "app_id": "website-studio",
                        "access": "public_capability",
                        "expires_at": (datetime.now(tz=UTC) + timedelta(minutes=15)).isoformat(),
                        "allowed_paths": [str(allowed_path)],
                        "file_response": {
                            "path": str(other_path),
                            "content_type": "video/mp4",
                        },
                    }
                ),
                encoding="utf-8",
            )

            status, _headers, body = _serve_file_gateway_manifest(
                root=root,
                manifest_root=manifest_root,
                token=token,
                app_id="website-studio",
                environ={"REQUEST_METHOD": "GET"},
            )

        self.assertEqual(status, "403 Forbidden")
        self.assertIn(b"file_gateway_forbidden", body)

    def test_media_route_secret_resolution_requests_no_app_secrets(self) -> None:
        for route_path in ("/api/apps/media-app/media", "/api/apps/media-app/backend/media"):
            with self.subTest(route_path=route_path):
                body = _backend_secret_request_body(body={}, method="GET", route_path=route_path)

                self.assertEqual(body, {"_app_secret_request": {"logical_names": [], "required": False}})

    def test_media_route_secret_resolution_accepts_encoded_query_request(self) -> None:
        secret_request = {"required": True, "selectors": [{"logical_names": ["google-drive-oauth-client-id"]}]}

        for route_path in ("/api/apps/media-app/media", "/api/apps/media-app/backend/media"):
            with self.subTest(route_path=route_path):
                body = _backend_secret_request_body(
                    body={},
                    method="GET",
                    route_path=route_path,
                    query={"stable_storage_file_id": "file_123", "_app_secret_request": json.dumps(secret_request)},
                )

                self.assertEqual(body["stable_storage_file_id"], "file_123")
                self.assertEqual(body["_app_secret_request"], secret_request)

    def test_backend_request_headers_include_safe_browser_context(self) -> None:
        headers = _backend_request_headers(
            {
                "CONTENT_TYPE": "application/json",
                "HTTP_RANGE": "bytes=2-5",
                "HTTP_ORIGIN": "https://studio.example",
                "HTTP_HOST": "studio.example",
                "HTTP_X_FORWARDED_PROTO": "https",
                "HTTP_COOKIE": "session=blocked",
                "HTTP_AUTHORIZATION": "Bearer blocked",
            }
        )

        self.assertEqual(headers["content_type"], "application/json")
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(headers["range"], "bytes=2-5")
        self.assertEqual(headers["origin"], "https://studio.example")
        self.assertEqual(headers["host"], "studio.example")
        self.assertEqual(headers["x-forwarded-proto"], "https")
        self.assertNotIn("cookie", headers)
        self.assertNotIn("authorization", headers)

    def test_app_secret_payload_uses_active_backend_grants_not_legacy_bindings(self) -> None:
        secret_store = _secret_store()
        state = _state(secret_store)
        secret = create_platform_secret(secret_store, label="Backend", raw_value="backend-secret", alias="backend-secret")
        bind_app_secret(
            secret_store,
            workspace_id="default",
            app_id="browser",
            logical_name="legacy",
            secret_ref=build_secret_ref(alias=secret.alias),
        )
        grant_app_secret_use(
            secret_store,
            workspace_id="default",
            app_id="browser",
            logical_name="api_token",
            secret_ref=build_secret_ref(alias=secret.alias),
            actions=["app.backend"],
            target_patterns=["maverick://app.backend/*"],
        )

        result = _resolve_app_secret_payload(
            state,  # type: ignore[arg-type]
            workspace_id="default",
            app_id="browser",
            allowed_logical_names=["api_token"],
        )

        self.assertEqual(result.secrets, {"api_token": "backend-secret"})
        self.assertEqual(result.errors, [])

    def test_app_secret_payload_rejects_legacy_backend_scoped_action(self) -> None:
        secret_store = _secret_store()
        state = _state(secret_store)
        secret = create_platform_secret(secret_store, label="Backend", raw_value="backend-secret", alias="backend-secret")
        grant_app_secret_use(
            secret_store,
            workspace_id="default",
            app_id="browser",
            logical_name="api_token",
            secret_ref=build_secret_ref(alias=secret.alias),
            actions=["app.secret.read"],
            target_patterns=["maverick://app.backend/*"],
        )

        with self.assertRaises(SecretPolicyError):
            _resolve_app_secret_payload(
                state,  # type: ignore[arg-type]
                workspace_id="default",
                app_id="browser",
                allowed_logical_names=["api_token"],
            )

    def test_app_secret_payload_rejects_legacy_action_without_backend_target(self) -> None:
        secret_store = _secret_store()
        state = _state(secret_store)
        secret = create_platform_secret(secret_store, label="Backend", raw_value="backend-secret", alias="backend-secret")
        grant_app_secret_use(
            secret_store,
            workspace_id="default",
            app_id="browser",
            logical_name="api_token",
            secret_ref=build_secret_ref(alias=secret.alias),
            actions=["app.secret.read"],
            target_patterns=["https://example.com/*"],
        )

        with self.assertRaises(SecretPolicyError):
            _resolve_app_secret_payload(
                state,  # type: ignore[arg-type]
                workspace_id="default",
                app_id="browser",
                allowed_logical_names=["api_token"],
            )

    def test_app_secret_payload_fails_closed_when_backend_grant_is_denied(self) -> None:
        secret_store = _secret_store()
        state = _state(secret_store)
        secret = create_platform_secret(secret_store, label="Backend", raw_value="backend-secret", alias="backend-secret")
        grant_app_secret_use(
            secret_store,
            workspace_id="default",
            app_id="browser",
            logical_name="api_token",
            secret_ref=build_secret_ref(alias=secret.alias),
            actions=["app.backend"],
            target_patterns=["maverick://app.backend/*"],
            expires_at=datetime.now(tz=UTC) - timedelta(minutes=1),
        )

        with self.assertRaises(SecretPolicyError):
            _resolve_app_secret_payload(
                state,  # type: ignore[arg-type]
                workspace_id="default",
                app_id="browser",
                allowed_logical_names=["api_token"],
            )

    def test_app_secret_payload_fails_closed_when_declared_grant_is_missing(self) -> None:
        secret_store = _secret_store()
        state = _state(secret_store)

        with self.assertRaises(SecretPolicyError):
            _resolve_app_secret_payload(
                state,  # type: ignore[arg-type]
                workspace_id="default",
                app_id="browser",
                allowed_logical_names=["api_token"],
                runtime_session_id="runtime-1",
            )
        audit = state.observability_store.list_audit(workspace_id="default", source_domain="secrets")
        self.assertEqual(audit[-1].action, "core.secrets.delivery")
        self.assertEqual(audit[-1].status, "failed")
        self.assertEqual(audit[-1].runtime_session_id, "runtime-1")
        self.assertEqual(audit[-1].payload["logical_name"], "api_token")
        events = state.observability_store.list_events(workspace_id="default")
        self.assertEqual(events[-1].event_type, "core.secrets.delivery")
        self.assertEqual(events[-1].event_plane, "runtime")
        self.assertEqual(events[-1].runtime_session_id, "runtime-1")

    def test_app_secret_payload_ignores_newer_non_backend_grants(self) -> None:
        secret_store = _secret_store()
        state = _state(secret_store)
        backend_secret = create_platform_secret(secret_store, label="Backend", raw_value="backend-secret", alias="backend-secret")
        autofill_secret = create_platform_secret(secret_store, label="Autofill", raw_value="autofill-secret", alias="autofill-secret")
        grant_app_secret_use(
            secret_store,
            workspace_id="default",
            app_id="browser",
            logical_name="api_token",
            secret_ref=build_secret_ref(alias=backend_secret.alias),
            actions=["app.backend"],
            target_patterns=["maverick://app.backend/*"],
            now=datetime.now(tz=UTC) - timedelta(minutes=1),
        )
        grant_app_secret_use(
            secret_store,
            workspace_id="default",
            app_id="browser",
            logical_name="api_token",
            secret_ref=build_secret_ref(alias=autofill_secret.alias),
            actions=["browser.autofill"],
            target_patterns=["https://example.com/*"],
        )

        result = _resolve_app_secret_payload(
            state,  # type: ignore[arg-type]
            workspace_id="default",
            app_id="browser",
            allowed_logical_names=["api_token"],
        )

        self.assertEqual(result.secrets, {"api_token": "backend-secret"})

    def test_app_secret_payload_uses_replacement_after_expired_grant(self) -> None:
        secret_store = _secret_store()
        state = _state(secret_store)
        expired_secret = create_platform_secret(secret_store, label="Expired", raw_value="expired-secret", alias="expired-secret")
        replacement_secret = create_platform_secret(
            secret_store,
            label="Replacement",
            raw_value="replacement-secret",
            alias="replacement-secret",
        )
        grant_app_secret_use(
            secret_store,
            workspace_id="default",
            app_id="browser",
            logical_name="api_token",
            secret_ref=build_secret_ref(alias=expired_secret.alias),
            actions=["app.backend"],
            target_patterns=["maverick://app.backend/*"],
            expires_at=datetime.now(tz=UTC) - timedelta(minutes=1),
        )
        grant_app_secret_use(
            secret_store,
            workspace_id="default",
            app_id="browser",
            logical_name="api_token",
            secret_ref=build_secret_ref(alias=replacement_secret.alias),
            actions=["app.backend"],
            target_patterns=["maverick://app.backend/*"],
        )

        result = _resolve_app_secret_payload(
            state,  # type: ignore[arg-type]
            workspace_id="default",
            app_id="browser",
            allowed_logical_names=["api_token"],
        )

        self.assertEqual(result.secrets, {"api_token": "replacement-secret"})
        self.assertEqual(result.errors, [])

    def test_app_secret_payload_can_report_denied_grants_when_not_fail_closed(self) -> None:
        secret_store = _secret_store()
        state = _state(secret_store)
        secret = create_platform_secret(secret_store, label="Backend", raw_value="backend-secret", alias="backend-secret")
        grant = grant_app_secret_use(
            secret_store,
            workspace_id="default",
            app_id="browser",
            logical_name="api_token",
            secret_ref=build_secret_ref(alias=secret.alias),
            actions=["app.backend"],
            target_patterns=["maverick://app.backend/*"],
            expires_at=datetime.now(tz=UTC) - timedelta(minutes=1),
        )

        result = _resolve_app_secret_payload(
            state,  # type: ignore[arg-type]
            workspace_id="default",
            app_id="browser",
            allowed_logical_names=["api_token"],
            fail_closed=False,
        )

        self.assertEqual(result.secrets, {})
        self.assertEqual(result.errors, [{"logical_name": "api_token", "grant_id": "", "error": "SecretGrantMissing"}])

    def test_app_secret_writes_create_grant_delivery_state(self) -> None:
        secret_store = _secret_store()
        state = _state(secret_store)
        result_payload = {"platform_secret_writes": [{"logical_name": "api_token", "raw_value": "written-secret"}]}

        persisted = _apply_app_secret_writes(
            state,  # type: ignore[arg-type]
            workspace_id="default",
            app_id="browser",
            allowed_logical_names=["api_token"],
            result=result_payload,
        )
        delivered = _resolve_app_secret_payload(
            state,  # type: ignore[arg-type]
            workspace_id="default",
            app_id="browser",
            allowed_logical_names=["api_token"],
        )

        self.assertNotIn("platform_secret_writes", result_payload)
        self.assertEqual(delivered.secrets, {"api_token": "written-secret"})
        self.assertTrue(persisted[0]["grant_id"])
        grant = secret_store.get_secret_grant(str(persisted[0]["grant_id"]))
        audit_actions = [item.action for item in state.observability_store.list_audit(workspace_id="default", source_domain="secrets")]
        self.assertEqual(grant.reason, "Created automatically for app backend secret write delivery.")
        self.assertIn("core.secrets.app_write.create", audit_actions)
        self.assertIn("core.secrets.grant.create.app_write", audit_actions)

    def test_app_secret_writes_can_scope_delivery_to_resource(self) -> None:
        secret_store = _secret_store()
        state = _state(secret_store)
        result_payload = {
            "platform_secret_writes": [
                {
                    "logical_name": "gmail-refresh-token",
                    "resource_type": "mail_connection",
                    "resource_id": "conn_1",
                    "raw_value": "refresh-token-one",
                },
                {
                    "logical_name": "gmail-refresh-token",
                    "resource_type": "mail_connection",
                    "resource_id": "conn_2",
                    "raw_value": "refresh-token-two",
                },
            ]
        }

        persisted = _apply_app_secret_writes(
            state,  # type: ignore[arg-type]
            workspace_id="default",
            app_id="mail",
            allowed_logical_names=["gmail-refresh-token"],
            result=result_payload,
            secret_consumers=_mail_secret_consumers(),
        )
        first = _resolve_app_secret_payload(
            state,  # type: ignore[arg-type]
            workspace_id="default",
            app_id="mail",
            allowed_logical_names=["gmail-refresh-token"],
            resource_type="mail_connection",
            resource_id="conn_1",
        )
        second = _resolve_app_secret_payload(
            state,  # type: ignore[arg-type]
            workspace_id="default",
            app_id="mail",
            allowed_logical_names=["gmail-refresh-token"],
            resource_type="mail_connection",
            resource_id="conn_2",
        )

        self.assertEqual(first.secrets, {"gmail-refresh-token": "refresh-token-one"})
        self.assertEqual(second.secrets, {"gmail-refresh-token": "refresh-token-two"})
        self.assertEqual(persisted[0]["resource_type"], "mail_connection")
        self.assertEqual(persisted[0]["resource_id"], "conn_1")
        self.assertNotEqual(persisted[0]["grant_id"], persisted[1]["grant_id"])

        rotate_payload = {
            "platform_secret_writes": [
                {
                    "logical_name": "gmail-refresh-token",
                    "resource_type": "mail_connection",
                    "resource_id": "conn_1",
                    "raw_value": "refresh-token-one-rotated",
                }
            ]
        }
        rotated = _apply_app_secret_writes(
            state,  # type: ignore[arg-type]
            workspace_id="default",
            app_id="mail",
            allowed_logical_names=["gmail-refresh-token"],
            result=rotate_payload,
            secret_consumers=_mail_secret_consumers(),
        )
        first_after_rotate = _resolve_app_secret_payload(
            state,  # type: ignore[arg-type]
            workspace_id="default",
            app_id="mail",
            allowed_logical_names=["gmail-refresh-token"],
            resource_type="mail_connection",
            resource_id="conn_1",
        )
        second_after_rotate = _resolve_app_secret_payload(
            state,  # type: ignore[arg-type]
            workspace_id="default",
            app_id="mail",
            allowed_logical_names=["gmail-refresh-token"],
            resource_type="mail_connection",
            resource_id="conn_2",
        )

        self.assertEqual(rotated[0]["grant_id"], persisted[0]["grant_id"])
        self.assertEqual(first_after_rotate.secrets, {"gmail-refresh-token": "refresh-token-one-rotated"})
        self.assertEqual(second_after_rotate.secrets, {"gmail-refresh-token": "refresh-token-two"})
        encoded_audit = str([item.payload for item in state.observability_store.list_audit(source_domain="secrets")])
        self.assertNotIn("refresh-token-one", encoded_audit)
        self.assertNotIn("refresh-token-two", encoded_audit)

    def test_app_secret_writes_rotate_existing_resource_scoped_base_target_grant(self) -> None:
        secret_store = _secret_store()
        state = _state(secret_store)
        secret = create_platform_secret(secret_store, label="Refresh", raw_value="old-token", alias="mail-refresh-conn-1")
        grant = grant_app_secret_use(
            secret_store,
            workspace_id="default",
            app_id="mail",
            logical_name="gmail-refresh-token",
            secret_ref=build_secret_ref(alias=secret.alias),
            actions=["app.backend"],
            target_patterns=[app_secret_target("backend")],
            resource_type="mail_connection",
            resource_id="conn_1",
        )

        persisted = _apply_app_secret_writes(
            state,  # type: ignore[arg-type]
            workspace_id="default",
            app_id="mail",
            allowed_logical_names=["gmail-refresh-token"],
            result={
                "platform_secret_writes": [
                    {
                        "logical_name": "gmail-refresh-token",
                        "resource_type": "mail_connection",
                        "resource_id": "conn_1",
                        "raw_value": "new-token",
                    }
                ]
            },
            secret_consumers=_mail_secret_consumers(),
        )
        delivered = _resolve_app_secret_payload(
            state,  # type: ignore[arg-type]
            workspace_id="default",
            app_id="mail",
            allowed_logical_names=["gmail-refresh-token"],
            resource_type="mail_connection",
            resource_id="conn_1",
        )
        saved_grant = secret_store.get_secret_grant(grant.grant_id)

        self.assertEqual(persisted[0]["grant_id"], grant.grant_id)
        self.assertEqual(delivered.secrets, {"gmail-refresh-token": "new-token"})
        self.assertEqual(saved_grant.resource_type, "mail_connection")
        self.assertEqual(saved_grant.resource_id, "conn_1")
        self.assertEqual(saved_grant.target_patterns, ["maverick://app.backend/*"])

    def test_app_secret_writes_enforce_declared_resource_scope(self) -> None:
        secret_store = _secret_store()
        state = _state(secret_store)

        with self.assertRaisesRegex(SecretPolicyError, "requires resource_type and resource_id"):
            _apply_app_secret_writes(
                state,  # type: ignore[arg-type]
                workspace_id="default",
                app_id="mail",
                allowed_logical_names=["gmail-refresh-token"],
                result={"platform_secret_writes": [{"logical_name": "gmail-refresh-token", "raw_value": "refresh-token"}]},
                secret_consumers=_mail_secret_consumers(),
            )
        with self.assertRaisesRegex(SecretPolicyError, "does not allow resource_type"):
            _apply_app_secret_writes(
                state,  # type: ignore[arg-type]
                workspace_id="default",
                app_id="mail",
                allowed_logical_names=["gmail-refresh-token"],
                result={
                    "platform_secret_writes": [
                        {
                            "logical_name": "gmail-refresh-token",
                            "resource_type": "email_thread",
                            "resource_id": "thread_1",
                            "raw_value": "refresh-token",
                        }
                    ]
                },
                secret_consumers=_mail_secret_consumers(),
            )
        with self.assertRaisesRegex(SecretPolicyError, "workspace-scoped"):
            _apply_app_secret_writes(
                state,  # type: ignore[arg-type]
                workspace_id="default",
                app_id="mail",
                allowed_logical_names=["gmail-oauth-client-id"],
                result={
                    "platform_secret_writes": [
                        {
                            "logical_name": "gmail-oauth-client-id",
                            "resource_type": "mail_connection",
                            "resource_id": "conn_1",
                            "raw_value": "client-id",
                        }
                    ]
                },
                secret_consumers=_mail_secret_consumers(),
            )

    def test_app_secret_payload_does_not_cross_resource_scopes(self) -> None:
        secret_store = _secret_store()
        state = _state(secret_store)
        workspace_secret = create_platform_secret(secret_store, label="Workspace", raw_value="workspace-secret", alias="workspace-secret")
        first_secret = create_platform_secret(secret_store, label="First", raw_value="first-secret", alias="first-secret")
        second_secret = create_platform_secret(secret_store, label="Second", raw_value="second-secret", alias="second-secret")
        grant_app_secret_use(
            secret_store,
            workspace_id="default",
            app_id="mail",
            logical_name="gmail-oauth-client-id",
            secret_ref=build_secret_ref(alias=workspace_secret.alias),
            actions=["app.backend"],
            target_patterns=["maverick://app.backend/*"],
        )
        grant_app_secret_use(
            secret_store,
            workspace_id="default",
            app_id="mail",
            logical_name="gmail-refresh-token",
            secret_ref=build_secret_ref(alias=first_secret.alias),
            actions=["app.backend"],
            target_patterns=["maverick://app.backend/*"],
            resource_type="mail_connection",
            resource_id="conn_1",
        )
        grant_app_secret_use(
            secret_store,
            workspace_id="default",
            app_id="mail",
            logical_name="gmail-refresh-token",
            secret_ref=build_secret_ref(alias=second_secret.alias),
            actions=["app.backend"],
            target_patterns=["maverick://app.backend/*"],
            resource_type="mail_connection",
            resource_id="conn_2",
        )

        first = _resolve_app_secret_payload(
            state,  # type: ignore[arg-type]
            workspace_id="default",
            app_id="mail",
            allowed_logical_names=["gmail-refresh-token"],
            resource_type="mail_connection",
            resource_id="conn_1",
        )
        workspace = _resolve_app_secret_payload(
            state,  # type: ignore[arg-type]
            workspace_id="default",
            app_id="mail",
            allowed_logical_names=["gmail-oauth-client-id"],
        )

        self.assertEqual(first.secrets, {"gmail-refresh-token": "first-secret"})
        self.assertEqual(workspace.secrets, {"gmail-oauth-client-id": "workspace-secret"})
        with self.assertRaises(SecretPolicyError):
            _resolve_app_secret_payload(
                state,  # type: ignore[arg-type]
                workspace_id="default",
                app_id="mail",
                allowed_logical_names=["gmail-refresh-token"],
            )
        with self.assertRaises(SecretPolicyError):
            _resolve_app_secret_payload(
                state,  # type: ignore[arg-type]
                workspace_id="default",
                app_id="mail",
                allowed_logical_names=["gmail-oauth-client-id"],
                resource_type="mail_connection",
                resource_id="conn_1",
            )
        with self.assertRaises(SecretPolicyError):
            _resolve_app_secret_payload(
                state,  # type: ignore[arg-type]
                workspace_id="default",
                app_id="mail",
                allowed_logical_names=["gmail-refresh-token"],
                resource_type="mail_connection",
                resource_id="conn_3",
            )


def _serve(root: Path, subpath: str, *, cross_origin: bool = False) -> tuple[str, dict[str, str]]:
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = dict(headers)

    serve_frontend(start_response, frontend_root=root, subpath=subpath, cross_origin=cross_origin)
    return str(captured["status"]), captured["headers"]  # type: ignore[return-value]


def _serve_file_response(*, root: Path, file_response: dict[str, object], environ: dict[str, str]) -> tuple[str, dict[str, str], bytes]:
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(
        _serve_app_file_response(
            environ=environ,
            start_response=start_response,
            file_response=file_response,
            allowed_roots=[root],
        )
    )
    return str(captured["status"]), captured["headers"], body  # type: ignore[return-value]


def _serve_file_gateway_manifest(
    *,
    root: Path,
    manifest_root: Path,
    token: str,
    app_id: str,
    environ: dict[str, str],
) -> tuple[str, dict[str, str], bytes]:
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(
        _serve_app_file_gateway_manifest(
            environ=environ,
            start_response=start_response,
            token=token,
            manifest_root=manifest_root,
            allowed_roots=[root],
            app_id=app_id,
        )
    )
    return str(captured["status"]), captured["headers"], body  # type: ignore[return-value]


def _secret_store() -> SecretDocumentStore:
    return SecretDocumentStore(
        SecretCollections(
            secrets=FakeCollection(),
            values=FakeCollection(),
            bindings=FakeCollection(),
            grants=FakeCollection(),
        ),
        key_loader=lambda: b"test-key",
    )


def _state(secret_store: SecretDocumentStore) -> SimpleNamespace:
    return SimpleNamespace(
        secret_store=secret_store,
        observability_store=ObservabilityDocumentStore(
            ObservabilityCollections(events=FakeCollection(), audit=FakeCollection(), metrics=FakeCollection())
        ),
    )


def _mail_secret_consumers() -> dict[str, dict[str, object]]:
    return {
        "gmail-oauth-client-id": {
            "backend": True,
            "cli_commands": ["mail"],
            "mcp_tools": [],
            "resource_scoped": False,
            "resource_types": [],
        },
        "gmail-refresh-token": {
            "backend": True,
            "cli_commands": ["mail"],
            "mcp_tools": [],
            "resource_scoped": True,
            "resource_types": ["mail_connection"],
        },
    }


if __name__ == "__main__":
    unittest.main()
