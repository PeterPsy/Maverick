from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from core.api.app_mounts import _apply_app_secret_writes, _read_backend_body, _resolve_app_secret_payload, backend_entrypoint_timeout_seconds, serve_frontend
from core.api.http import HttpRequestError
from core.apps.contracts import build_app_contract, build_app_hook_timeouts, build_parsed_app_contract
from core.observability.store import ObservabilityCollections, ObservabilityDocumentStore
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


def _serve(root: Path, subpath: str, *, cross_origin: bool = False) -> tuple[str, dict[str, str]]:
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = dict(headers)

    serve_frontend(start_response, frontend_root=root, subpath=subpath, cross_origin=cross_origin)
    return str(captured["status"]), captured["headers"]  # type: ignore[return-value]


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


if __name__ == "__main__":
    unittest.main()
