#!/usr/bin/env python3
"""Serve a synthetic, persistent Maverick installation for the WP10 browser E2E."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys


APP_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = APP_ROOT.parents[1]
SERVICE_ROOT = APP_ROOT / "service"

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SERVICE_ROOT))

from core.api.asgi_application import PlatformAsgiHost  # noqa: E402
from core.api.backend_recovery import start_backend_restart_recovery  # noqa: E402
from core.api.background_hooks import start_background_hook_scheduler  # noqa: E402
from core.api.platform_state import bootstrap_platform_state  # noqa: E402
from core.api.sidecar_control import start_sidecar_control_server  # noqa: E402
from core.api.sidecar_prewarm import start_declared_sidecar_prewarms  # noqa: E402
from core.apps.artifact_mounts import platform_artifact_store_root  # noqa: E402
from core.apps.dependencies import save_app_dependency_selection  # noqa: E402
from core.apps.service import install_store_app, register_app_source_from_contract  # noqa: E402
from core.providers.service import configure_workspace_provider  # noqa: E402
from core.shared.entrypoints import EntrypointShutdownController  # noqa: E402
from core.workspaces.service import create_workspace, set_active_workspace_for_user  # noqa: E402
from opendesign_artifact import read_bundle_manifest, selected_asset, validate_bundle_manifest  # noqa: E402
from opendesign_artifact_audit import fully_audited_web_overlay  # noqa: E402
from opendesign_artifact_store import OpenDesignArtifactStore  # noqa: E402
from opendesign_bootstrap import bootstrap_empty_generation  # noqa: E402
from opendesign_runtime import protected_activation_inventory, verified_overlay_from_store  # noqa: E402
from opendesign_web_activation import activate_web_overlay  # noqa: E402


WORKSPACES = ("default", "workspace-b")
APP_IDS = ("base-shell", "storage", "design-studio")
SETUP_MARKER = ".maverick-wp10-product-fixture.json"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--web-overlay-sha256", required=True)
    return parser.parse_args()


def _prepare_root(root: Path) -> None:
    for name in ("core", "apps", "workspaces", "scripts"):
        (root / name).mkdir(parents=True, exist_ok=True)
    agents = root / "AGENTS.md"
    if not agents.exists():
        agents.write_text("# Synthetic WP10 product fixture\n", encoding="utf-8")
    for app_id in APP_IDS:
        target = root / "apps" / app_id
        if not target.exists():
            target.symlink_to(REPO_ROOT / "apps" / app_id, target_is_directory=True)


def _build_runtime_fixture(root: Path) -> Path:
    compiler = shutil.which("cc")
    if not compiler:
        raise RuntimeError("The WP10 external runtime fixture requires a C compiler.")
    output = root / "fixture-bin" / "vendor" / "maverick-wp10" / "codex" / "codex"
    output.parent.mkdir(parents=True, exist_ok=True)
    source = APP_ROOT / "tests" / "fixtures" / "codex_app_server_fixture.c"
    build_receipt = output.with_name("build-receipt.json")
    source_sha256 = sha256(source.read_bytes()).hexdigest()
    try:
        receipt = json.loads(build_receipt.read_text(encoding="utf-8"))
        reusable = (
            receipt == {"schema_version": 1, "source_sha256": source_sha256}
            and output.is_file()
            and not output.is_symlink()
            and os.access(output, os.X_OK)
        )
    except (OSError, json.JSONDecodeError):
        reusable = False
    if reusable:
        return output
    generated_include = root / "fixture-bin" / "build" / "codex_resume_archive_fixture.h"
    _write_resume_archive_fixture_header(generated_include)
    subprocess.run(
        [
            compiler,
            "-std=c11",
            "-O2",
            "-pthread",
            "-static",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(generated_include.parent),
            "-o",
            str(output),
            str(source),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    output.chmod(0o755)
    build_receipt.write_text(
        json.dumps(
            {"schema_version": 1, "source_sha256": source_sha256},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return output


def _write_resume_archive_fixture_header(output: Path) -> None:
    """Generate a deterministic SQLite image consumed by the external C fixture."""
    output.parent.mkdir(parents=True, exist_ok=True)
    database = output.with_suffix(".sqlite")
    placeholder = "Z" * 512
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA page_size=4096")
        connection.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO threads (id, rollout_path) VALUES (?, ?)",
            ("thread-maverick-wp10", placeholder),
        )
        connection.commit()
    image = database.read_bytes()
    database.unlink()
    marker = placeholder.encode("ascii")
    if image.count(marker) != 1:
        raise RuntimeError("The generated Codex resume archive placeholder is not unique.")
    rows = [
        ", ".join(f"0x{byte:02x}" for byte in image[index : index + 16])
        for index in range(0, len(image), 16)
    ]
    output.write_text(
        "#ifndef MAVERICK_CODEX_RESUME_ARCHIVE_FIXTURE_H\n"
        "#define MAVERICK_CODEX_RESUME_ARCHIVE_FIXTURE_H\n"
        "static const unsigned char maverick_resume_archive_template[] = {\n    "
        + ",\n    ".join(rows)
        + "\n};\n"
        + f"static const size_t maverick_resume_archive_template_size = {len(image)};\n"
        + "static const size_t maverick_resume_rollout_path_size = 512;\n"
        + "#endif\n",
        encoding="ascii",
    )


def _install_app(state, root: Path, workspace_id: str, app_id: str) -> None:
    source = register_app_source_from_contract(
        state.app_store,
        source_kind="platform",
        source_path=str(root / "apps" / app_id),
    )
    install_store_app(
        state.app_store,
        source_id=source.source_id,
        workspace_id=workspace_id,
        start_path=root,
        observability_store=state.observability_store,
    )


def _bootstrap_generation(root: Path, workspace_id: str, web_overlay_sha256: str) -> None:
    manifest = read_bundle_manifest(SERVICE_ROOT / "opendesign_bundle.json")
    validate_bundle_manifest(manifest, require_artifact_digest=True)
    asset = selected_asset(manifest, require_artifact_digest=True)
    store = OpenDesignArtifactStore(
        platform_artifact_store_root(REPO_ROOT) / "design-studio" / "opendesign"
    )
    runtime = store.fast_runtime(
        str(asset["sha256"]),
        file_manifest_sha256=str(asset["file_manifest_sha256"]),
        opendesign_version=str(manifest["upstream"]["release_version"]),
        upstream_commit=str(manifest["upstream"]["commit"]),
    )
    overlay = store.fast_web_overlay(
        web_overlay_sha256,
        runtime_artifact_sha256=asset["sha256"],
    )
    generation_root = root / "workspaces" / workspace_id / "data" / "design-studio" / "opendesign"
    control_path = generation_root / "control.json"
    if control_path.exists() or control_path.is_symlink():
        control, verified_artifacts, verified_overlays = protected_activation_inventory(
            store=store,
            generation_root=generation_root,
        )
        audited_overlay = fully_audited_web_overlay(
            store,
            web_overlay_sha256,
            runtime_artifact_sha256=control.active.runtime_artifact_sha256,
        )
        verified_overlays[audited_overlay.artifact_sha256] = verified_overlay_from_store(
            audited_overlay
        )
        if control.active.web_overlay_sha256 == audited_overlay.artifact_sha256:
            return
        outcome = activate_web_overlay(
            generation_root,
            target_web_overlay_sha256=audited_overlay.artifact_sha256,
            web_activation_id=f"web_e2e_{audited_overlay.artifact_sha256[:16]}",
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
            restart_sidecars=lambda: {"ready": True, "service_count": 1},
        )
        if not outcome.activated or outcome.rolled_back:
            raise RuntimeError("The synthetic OpenDesign candidate overlay did not activate.")
        return
    bootstrap_empty_generation(
        generation_root,
        artifact_sha256=runtime.artifact_sha256,
        web_overlay_sha256=overlay.artifact_sha256,
        opendesign_version=str(runtime.receipt["opendesign_version"]),
        verified_artifacts={
            runtime.artifact_sha256: str(runtime.receipt["opendesign_version"])
        },
        verified_overlays={
            overlay.artifact_sha256: {
                "od_version": str(overlay.receipt["opendesign_version"]),
                "compatible_runtime_artifact_sha256": overlay.receipt[
                    "compatible_runtime_artifact_sha256"
                ],
            }
        },
    )


def _initial_setup(state, root: Path, web_overlay_sha256: str) -> None:
    admin = state.identity_store.get_user_by_username("admin")
    workspace_b = create_workspace(
        state.workspace_store,
        name="Workspace B",
        description="Synthetic isolation peer for Design Studio WP10.",
        created_by_user_id=admin.user_id,
    )
    if workspace_b.workspace_id != "workspace-b":
        raise RuntimeError("Synthetic workspace id drifted.")
    for workspace_id in WORKSPACES:
        for app_id in APP_IDS:
            _install_app(state, root, workspace_id, app_id)
        for alias in ("storage-read", "storage-write"):
            save_app_dependency_selection(
                state.app_store,
                workspace_id=workspace_id,
                consumer_app_id="design-studio",
                alias=alias,
                provider_app_ids=["storage"],
                workspace_store=state.workspace_store,
                start_path=root,
            )
        configure_workspace_provider(state.provider_store, workspace_id=workspace_id, provider_id="codex")
        _bootstrap_generation(root, workspace_id, web_overlay_sha256)
    set_active_workspace_for_user(state.workspace_store, user_id=admin.user_id, workspace_id="default")
    (root / SETUP_MARKER).write_text(
        json.dumps({"schema_version": 1, "workspaces": list(WORKSPACES)}, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    arguments = _arguments()
    root = arguments.root.resolve()
    _prepare_root(root)
    os.environ["MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS"] = "1"
    os.environ["MAVERICK_ADMIN_USERNAME"] = "admin"
    os.environ["MAVERICK_ADMIN_PASSWORD"] = "maverick"
    os.environ["MAVERICK_CODEX_COMMAND"] = str(_build_runtime_fixture(root))
    os.environ["MAVERICK_SIDECAR_ORIGIN_MODE"] = "local"
    os.environ["MAVERICK_SIDECAR_CONTROL_SOCKET"] = str(
        root / "tmp/maverick-sidecar-control.sock"
    )
    state = bootstrap_platform_state(
        start_path=root,
        install_builtin_apps=False,
        register_builtin_provider_definitions=True,
    )
    if not (root / SETUP_MARKER).is_file():
        _initial_setup(state, root, arguments.web_overlay_sha256)
    shutdown_controller = EntrypointShutdownController()
    prewarm_threads = start_declared_sidecar_prewarms(
        state,
        trigger="core_start",
        shutdown_controller=shutdown_controller,
    )
    start_backend_restart_recovery(state, after_threads=prewarm_threads)
    start_background_hook_scheduler(state, shutdown_controller=shutdown_controller)
    start_sidecar_control_server(state, shutdown_controller=shutdown_controller)
    app = PlatformAsgiHost(state, shutdown_controller=shutdown_controller)
    import uvicorn

    print(json.dumps({"ready": True, "port": arguments.port, "workspaces": list(WORKSPACES)}), flush=True)
    try:
        uvicorn.run(app, host="127.0.0.1", port=arguments.port, log_level="warning", access_log=False)
    finally:
        shutdown_controller.begin_shutdown()


if __name__ == "__main__":
    main()
