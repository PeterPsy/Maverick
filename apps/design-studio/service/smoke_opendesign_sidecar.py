"""Smoke the materialized OpenDesign sidecar through Maverick's proxy."""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any, Iterator


REPO_ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = REPO_ROOT / "apps" / "design-studio"
SERVICE_ROOT = APP_ROOT / "service"
BUNDLE_REGISTRY = SERVICE_ROOT / "vendor" / "open-design"
WORKSPACE_ID = "default"
APP_ID = "design-studio"

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SERVICE_ROOT))
sys.path.insert(0, str(APP_ROOT / "backend"))

from core.api.platform_host import PlatformHost  # noqa: E402
from core.api.platform_state import bootstrap_platform_state  # noqa: E402
from core.apps.dependencies import save_app_dependency_selection  # noqa: E402
from core.apps.service import install_store_app, register_app_source_from_contract  # noqa: E402
from core.shared.entrypoints import EntrypointShutdownController  # noqa: E402
from opendesign_artifact import (  # noqa: E402
    ArtifactError,
    read_bundle_manifest,
    selected_asset,
    validate_bundle_manifest,
)
from opendesign_bootstrap import bootstrap_empty_generation  # noqa: E402
from opendesign_materialization import discover_verified_bundles  # noqa: E402
from opendesign_web_release import canonical_web_overlay  # noqa: E402
from runtime_bridge import build_result_package, reserve_run, store_for_payload  # noqa: E402


def main() -> None:
    bundle_summary, bundle_dir, web_static_dir = _assert_bundle_materialized()
    keep_temporary = os.environ.get("MAVERICK_KEEP_SIDECAR_SMOKE_TEMP") == "1"
    with TemporaryDirectory(delete=not keep_temporary) as temp_dir:
        repo_root = Path(temp_dir) / "maverick"
        _prepare_temporary_repo(repo_root)
        with _test_platform_env():
            state = bootstrap_platform_state(
                start_path=repo_root,
                install_builtin_apps=False,
                register_builtin_provider_definitions=False,
            )
            _install_platform_app(state, repo_root, "storage")
            _install_platform_app(state, repo_root, APP_ID)
            _select_storage_dependencies(state, repo_root)
            _prepare_smoke_generation(repo_root, bundle_summary)
            shutdown = EntrypointShutdownController()
            try:
                app = PlatformHost(state, start_path=repo_root, shutdown_controller=shutdown)
                cookie = _login(app)
                route_results = _smoke_proxy_routes(
                    app,
                    cookie=cookie,
                    expected_version=bundle_summary["runtime_reported_version"],
                    web_static_dir=web_static_dir,
                )
                adapter_result = _smoke_adapter(app, cookie=cookie, repo_root=repo_root)
                launcher_status = _launcher_status(
                    repo_root,
                    expected_artifact_sha256=bundle_summary["artifact_sha256"],
                )
            finally:
                shutdown.begin_shutdown()
        if keep_temporary:
            print(f"Retained sidecar smoke root: {repo_root}", file=sys.stderr)
    print(
        json.dumps(
            {
                "ok": True,
                "bundle": bundle_summary,
                "launcher": {
                    "mode": launcher_status.get("mode"),
                    "bundle_configured": launcher_status.get("bundle_configured"),
                    "detail": launcher_status.get("detail"),
                },
                "routes": route_results,
                "adapter": adapter_result,
            },
            indent=2,
            ensure_ascii=True,
        )
    )


def _assert_bundle_materialized() -> tuple[dict[str, Any], Path, Path]:
    manifest = read_bundle_manifest(SERVICE_ROOT / "opendesign_bundle.json")
    try:
        validate_bundle_manifest(manifest, require_artifact_digest=True)
        asset = selected_asset(manifest, require_artifact_digest=True)
    except ArtifactError as error:
        raise SystemExit(f"Pinned OpenDesign artifact is unavailable: {error}") from error
    bundles = discover_verified_bundles(BUNDLE_REGISTRY)
    bundle = bundles.get(asset["sha256"])
    if bundle is None:
        raise SystemExit("Pinned OpenDesign artifact is not materialized.")
    if (
        bundle.file_manifest_sha256 != asset["file_manifest_sha256"]
        or bundle.opendesign_version != manifest["upstream"]["release_version"]
        or bundle.upstream_commit != manifest["upstream"]["commit"]
    ):
        raise SystemExit("Pinned OpenDesign materialization metadata does not match the manifest.")
    required = [
        "maverick/materialized.json",
        "maverick/manifest.json",
        "maverick/oci.json",
        "maverick/boundary-patch.json",
        "maverick/sbom.cdx.json",
        "maverick/licenses.json",
        "maverick/NOTICE",
        "runtime/lib/ld-musl-x86_64.so.1",
        "runtime/bin/node",
        "app/apps/daemon/package.json",
        "app/apps/daemon/node_modules",
        "app/apps/daemon/dist/cli.js",
    ]
    missing = [relative for relative in required if not (bundle.path / relative).exists()]
    forbidden = [
        "app/apps/desktop",
        "app/apps/landing-page",
        "app/apps/packaged",
        "app/apps/web/out",
        "app/apps/telemetry-worker",
        "charts",
        "deploy",
        "e2e",
        "plugins/marketplaces",
        "tools",
    ]
    present_forbidden = [relative for relative in forbidden if (bundle.path / relative).exists()]
    if missing or present_forbidden:
        raise SystemExit(
            json.dumps(
                {
                    "error": "opendesign_bundle_not_phase3_ready",
                    "missing": missing,
                    "forbidden_paths": present_forbidden,
                },
                indent=2,
            )
        )
    overlay, _overlays = canonical_web_overlay(
        SERVICE_ROOT / "vendor/open-design-web",
        trust_contract=SERVICE_ROOT / "opendesign_web_trust.json",
        runtime_artifact_sha256=bundle.artifact_sha256,
        od_version=bundle.opendesign_version,
        upstream_commit=bundle.upstream_commit,
    )
    return {
        "path": str(bundle.path.relative_to(REPO_ROOT)),
        "mode": "verified-materialized-artifact",
        "release_version": manifest["upstream"]["release_version"],
        "runtime_reported_version": manifest["upstream"]["root_package_version"],
        "upstream_commit": manifest["upstream"]["commit"],
        "artifact_sha256": bundle.artifact_sha256,
        "web_overlay_sha256": overlay.web_overlay_sha256,
        "file_manifest_sha256": bundle.file_manifest_sha256,
    }, bundle.path, overlay.static_dir


def _prepare_smoke_generation(repo_root: Path, bundle_summary: dict[str, Any]) -> None:
    generation_root = repo_root / "workspaces" / WORKSPACE_ID / "data" / APP_ID / "opendesign"
    bootstrap_empty_generation(
        generation_root,
        artifact_sha256=bundle_summary["artifact_sha256"],
        web_overlay_sha256=bundle_summary["web_overlay_sha256"],
        opendesign_version=bundle_summary["release_version"],
        verified_artifacts={bundle_summary["artifact_sha256"]: bundle_summary["release_version"]},
        verified_overlays={
            bundle_summary["web_overlay_sha256"]: {
                "od_version": bundle_summary["release_version"],
                "compatible_runtime_artifact_sha256": [bundle_summary["artifact_sha256"]],
            }
        },
    )


def _prepare_temporary_repo(repo_root: Path) -> None:
    for name in ("core", "apps", "workspaces", "scripts"):
        (repo_root / name).mkdir(parents=True, exist_ok=True)
    (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
    (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
    (repo_root / "apps" / "storage").symlink_to(REPO_ROOT / "apps" / "storage", target_is_directory=True)
    (repo_root / "apps" / APP_ID).symlink_to(APP_ROOT, target_is_directory=True)


@contextmanager
def _test_platform_env() -> Iterator[None]:
    keys = ("MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS", "MAVERICK_ADMIN_USERNAME", "MAVERICK_ADMIN_PASSWORD")
    previous = {key: os.environ.get(key) for key in keys}
    os.environ["MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS"] = "1"
    os.environ["MAVERICK_ADMIN_USERNAME"] = "admin"
    os.environ["MAVERICK_ADMIN_PASSWORD"] = "maverick"
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _install_platform_app(state: Any, repo_root: Path, app_id: str) -> None:
    source = register_app_source_from_contract(
        state.app_store,
        source_kind="platform",
        source_path=str(repo_root / "apps" / app_id),
    )
    install_store_app(
        state.app_store,
        source_id=source.source_id,
        workspace_id=WORKSPACE_ID,
        start_path=repo_root,
        observability_store=state.observability_store,
    )


def _select_storage_dependencies(state: Any, repo_root: Path) -> None:
    for alias in ("storage-read", "storage-write"):
        save_app_dependency_selection(
            state.app_store,
            workspace_id=WORKSPACE_ID,
            consumer_app_id=APP_ID,
            alias=alias,
            provider_app_ids=["storage"],
            workspace_store=state.workspace_store,
            start_path=repo_root,
        )


def _login(app: PlatformHost) -> str:
    status, body, headers = _invoke(
        app,
        "/api/auth/login",
        method="POST",
        body={"username": "admin", "password": "maverick"},
        origin=True,
    )
    if status != 200:
        raise SystemExit(f"Login failed with HTTP {status}: {body.decode('utf-8', 'replace')}")
    return headers["Set-Cookie"].split(";", 1)[0]


def _smoke_proxy_routes(
    app: PlatformHost,
    *,
    cookie: str,
    expected_version: str,
    web_static_dir: Path,
) -> list[dict[str, Any]]:
    next_asset = _next_asset_path(web_static_dir)
    checks = [
        ("/api/apps/design-studio/sidecars/opendesign/index.html", "GET", 200),
        (f"/api/apps/design-studio/sidecars/opendesign/{next_asset}", "GET", 200),
        ("/api/apps/design-studio/sidecars/opendesign/api/ready", "GET", 200),
        ("/api/apps/design-studio/sidecars/opendesign/api/version", "GET", 200),
        ("/api/apps/design-studio/sidecars/opendesign/api/import/folder", "POST", 403),
        ("/api/apps/design-studio/sidecars/opendesign/api/media/config", "GET", 200),
    ]
    results: list[dict[str, Any]] = []
    for path, method, expected_status in checks:
        status, body, _headers = _invoke(
            app,
            path,
            method=method,
            body={} if method == "POST" else None,
            cookie=cookie,
            origin=method == "POST",
        )
        if status != expected_status:
            raise SystemExit(f"{path} returned HTTP {status}, expected {expected_status}: {body[:500]!r}")
        decoded = _decode_json_object(body)
        if path.endswith("/api/ready") and not decoded.get("ready"):
            raise SystemExit(f"{path} did not return ready=true: {decoded}")
        version = decoded.get("version")
        version_text = version.get("version") if isinstance(version, dict) else version
        if path.endswith("/api/version") and version_text != expected_version:
            raise SystemExit(f"{path} returned unexpected version payload: {decoded}")
        if path.endswith("/api/import/folder") and decoded.get("error") != "sidecar_route_blocked":
            raise SystemExit(f"{path} returned unexpected blocked payload: {decoded}")
        if path.endswith("/api/media/config") and decoded.get("sidecar_reached") is not False:
            raise SystemExit(f"{path} was not handled by core: {decoded}")
        results.append({"method": method, "path": path, "status": status})
    return results


def _smoke_adapter(app: PlatformHost, *, cookie: str, repo_root: Path) -> dict[str, Any]:
    """Exercise canonical create/import/export against the official daemon."""
    data_root = repo_root / "workspaces" / WORKSPACE_ID / "data" / APP_ID
    legacy_state = data_root / "state.json"
    legacy_bytes = b'{"schema_version":"1","projects":[]}\n'
    legacy_state.write_bytes(legacy_bytes)
    legacy_state.chmod(0o400)
    uploaded = repo_root / "workspaces" / WORKSPACE_ID / "storage" / "uploaded"
    uploaded.mkdir(parents=True, exist_ok=True)
    source_bytes = b"# Governed import\n\nOfficial OpenDesign adapter smoke.\n"
    (uploaded / "wp8-brief.md").write_bytes(source_bytes)

    create_status, create_body, _headers = _invoke(
        app,
        "/api/apps/design-studio/backend",
        method="POST",
        body={"action": "create_project", "arguments": {"name": "WP8 official adapter smoke"}},
        cookie=cookie,
        origin=True,
    )
    created = _decode_json_object(create_body)
    if create_status != 200 or not str(created.get("od_project_id") or "").startswith("od_maverick_"):
        raise SystemExit(f"Canonical OpenDesign project create failed: HTTP {create_status}: {created}")
    project_id = str(created["od_project_id"])

    import_status, import_body, _headers = _invoke(
        app,
        "/api/apps/design-studio/backend",
        method="POST",
        body={
            "action": "import_from_storage",
            "arguments": {
                "project_id": project_id,
                "workspace_relative_path": "storage/uploaded/wp8-brief.md",
            },
        },
        cookie=cookie,
        origin=True,
    )
    imported = _decode_json_object(import_body)
    dependency_results = imported.get("dependency_backend_request_results")
    adapter_after_import = _backend_state(app, cookie=cookie)
    import_jobs = adapter_after_import.get("import_jobs") if isinstance(adapter_after_import.get("import_jobs"), list) else []
    import_record = import_jobs[-1] if import_jobs and isinstance(import_jobs[-1], dict) else {}
    if (
        import_status != 200
        or import_record.get("status") != "imported"
        or import_record.get("sha256") != sha256(source_bytes).hexdigest()
        or not isinstance(dependency_results, list)
        or [item.get("status") for item in dependency_results] != ["completed"]
    ):
        raise SystemExit(f"Governed Storage import failed: HTTP {import_status}: {imported}")

    bridge_payload = {
        "app_id": APP_ID,
        "workspace_id": WORKSPACE_ID,
        "data_root": str(data_root),
        "sidecar_id": "opendesign",
    }
    correlation, inserted = reserve_run(
        bridge_payload,
        project_id=project_id,
        conversation_id="od_conversation_wp8_smoke",
        assistant_message_id="od_message_wp8_smoke",
        client_request_id="wp8-official-adapter-smoke",
        agent_id="maverick",
    )
    if not inserted:
        raise SystemExit("WP8 smoke correlation unexpectedly existed.")

    def terminal(record: dict[str, Any]) -> dict[str, Any]:
        record["runtime_session_id"] = "runtime_wp8_smoke"
        record["turn_id"] = "turn_wp8_smoke"
        record["stream_id"] = "stream_wp8_smoke"
        record["status"] = "succeeded"
        record["result_package"] = build_result_package(record, files=[])
        record["terminal_package_written"] = True
        return record

    correlation = store_for_payload(bridge_payload).update(correlation["od_run_id"], terminal)
    run_id = str(correlation["od_run_id"])
    export_status, export_body, _headers = _invoke(
        app,
        "/api/apps/design-studio/backend",
        method="POST",
        body={
            "action": "export_to_storage",
            "arguments": {"project_id": project_id, "run_id": run_id},
        },
        cookie=cookie,
        origin=True,
    )
    exported = _decode_json_object(export_body)
    export_results = exported.get("dependency_backend_request_results")
    adapter_after_export = _backend_state(app, cookie=cookie)
    export_jobs = adapter_after_export.get("export_jobs") if isinstance(adapter_after_export.get("export_jobs"), list) else []
    export_record = export_jobs[-1] if export_jobs and isinstance(export_jobs[-1], dict) else {}
    generated_root = repo_root / "workspaces" / WORKSPACE_ID / "storage" / "generated"
    export_root = generated_root / "design-studio" / project_id / run_id
    expected_files = [export_root / "project-files.zip", export_root / "result-package.json", export_root / "manifest.json"]
    if (
        export_status != 200
        or export_record.get("status") != "exported"
        or not isinstance(export_results, list)
        or [item.get("status") for item in export_results] != ["completed", "completed", "completed"]
        or any(not path.is_file() for path in expected_files)
    ):
        raise SystemExit(f"Governed Storage export failed: HTTP {export_status}: {exported}")
    manifest = json.loads((export_root / "manifest.json").read_text(encoding="utf-8"))
    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), list) else []
    by_path = {item.get("workspace_relative_path"): item for item in artifacts if isinstance(item, dict)}
    for path in expected_files[:-1]:
        relative = f"storage/generated/{path.relative_to(generated_root).as_posix()}"
        entry = by_path.get(relative)
        if not isinstance(entry, dict) or entry.get("sha256") != sha256(path.read_bytes()).hexdigest():
            raise SystemExit(f"Export manifest digest mismatch for {relative}.")
    if manifest.get("od_project_id") != project_id or manifest.get("od_run_id") != run_id:
        raise SystemExit("Export manifest canonical identity mismatch.")
    if legacy_state.read_bytes() != legacy_bytes or legacy_state.stat().st_mode & 0o777 != 0o400:
        raise SystemExit("Adapter modified the sealed legacy state.")
    adapter_state = json.loads((data_root / "adapter-state.json").read_text(encoding="utf-8"))
    if "projects" in adapter_state or (data_root / "imports").exists() or (data_root / "exports").exists():
        raise SystemExit("Adapter duplicated OpenDesign project or file storage.")
    return {
        "od_project_id": project_id,
        "od_run_id": run_id,
        "import_sha256": import_record["sha256"],
        "export_paths": [f"storage/generated/{path.relative_to(generated_root).as_posix()}" for path in expected_files],
        "manifest_artifact_count": len(artifacts),
        "legacy_state_preserved": True,
    }


def _backend_state(app: PlatformHost, *, cookie: str) -> dict[str, Any]:
    status, body, _headers = _invoke(
        app,
        "/api/apps/design-studio/backend",
        method="POST",
        body={"action": "state"},
        cookie=cookie,
        origin=True,
    )
    payload = _decode_json_object(body)
    state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    if status != 200:
        raise SystemExit(f"Design Studio state failed: HTTP {status}: {payload}")
    return state


def _next_asset_path(web_static_dir: Path) -> str:
    static_root = web_static_dir / "_next"
    for path in sorted(static_root.rglob("*")):
        if path.is_file() and path.suffix in {".js", ".css"}:
            return path.relative_to(web_static_dir).as_posix()
    raise SystemExit("OpenDesign web overlay has no _next JavaScript or CSS asset to smoke.")


def _launcher_status(repo_root: Path, *, expected_artifact_sha256: str) -> dict[str, Any]:
    status_path = repo_root / "workspaces" / WORKSPACE_ID / "data" / APP_ID / "opendesign" / "launcher-status.json"
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    if payload.get("mode") != "oci-musl-runtime":
        raise SystemExit(f"Launcher did not use oci-musl-runtime mode: {payload}")
    if not payload.get("bundle_configured"):
        raise SystemExit(f"Launcher did not report bundle_configured=true: {payload}")
    active = payload.get("active")
    if not isinstance(active, dict) or active.get("runtime_artifact_sha256") != expected_artifact_sha256:
        raise SystemExit(f"Launcher did not bind the expected artifact generation: {payload}")
    return payload


def _invoke(
    app: PlatformHost,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    cookie: str | None = None,
    origin: bool = False,
) -> tuple[int, bytes, dict[str, str]]:
    payload = b"" if body is None else json.dumps(body).encode("utf-8")
    headers: dict[str, str] = {}
    environ = {
        "PATH_INFO": path,
        "REQUEST_METHOD": method,
        "CONTENT_LENGTH": str(len(payload)),
        "CONTENT_TYPE": "application/json",
        "QUERY_STRING": "",
        "wsgi.input": BytesIO(payload),
        "HTTP_HOST": "testserver",
        "SERVER_NAME": "testserver",
    }
    if cookie is not None:
        environ["HTTP_COOKIE"] = cookie
    if origin:
        environ["HTTP_ORIGIN"] = "http://testserver"

    def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
        headers.update(dict(response_headers))
        headers["__status__"] = status

    result = b"".join(app(environ, start_response))
    return int(headers["__status__"].split()[0]), result, headers


def _decode_json_object(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


if __name__ == "__main__":
    main()
