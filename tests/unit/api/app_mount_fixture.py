"""Domain fixtures extracted without changing assertions."""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from core.api.app_mounts import _serve_app_file_gateway_manifest, _serve_app_file_response, serve_frontend
from core.apps.frontend_assets import FRONTEND_ASSET_MANIFEST_NAME
from core.observability.store import ObservabilityCollections, ObservabilityDocumentStore
from core.secrets.store import SecretCollections, SecretDocumentStore
from tests.support.collections import FakeCollection

def _serve(root: Path, subpath: str, *, cross_origin: bool = False) -> tuple[str, dict[str, str]]:
    status, headers, _body = _serve_body(root, subpath, cross_origin=cross_origin)
    return status, headers


def _serve_body(root: Path, subpath: str, *, cross_origin: bool = False, environ: dict[str, str] | None = None) -> tuple[str, dict[str, str], bytes]:
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(serve_frontend(start_response, frontend_root=root, subpath=subpath, cross_origin=cross_origin, environ=environ))
    return str(captured["status"]), captured["headers"], body  # type: ignore[return-value]


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


def _write_asset_manifest(root: Path, *, immutable_paths: list[str]) -> None:
    index = root / "index.html"
    if not index.exists():
        index.write_text("<!doctype html>", encoding="utf-8")

    def record(relative: str) -> dict[str, object]:
        body = (root / relative).read_bytes()
        return {"path": relative, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}

    payload = {
        "schema": "loopino.frontend-assets.v2",
        "build_id": "a" * 64,
        "entrypoints": ["index.html"],
        "immutable": [record(path) for path in immutable_paths],
        "revalidated": [record("index.html")],
    }
    (root / FRONTEND_ASSET_MANIFEST_NAME).write_text(json.dumps(payload), encoding="utf-8")


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
