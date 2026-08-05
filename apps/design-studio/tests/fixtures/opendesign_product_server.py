#!/usr/bin/env python3
"""Serve a synthetic, persistent Maverick installation for the WP10 browser E2E."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


APP_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = APP_ROOT.parents[1]
SERVICE_ROOT = APP_ROOT / "service"

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SERVICE_ROOT))

from core.api.asgi_application import PlatformAsgiHost  # noqa: E402
from core.api.backend_recovery import start_backend_restart_recovery  # noqa: E402
from core.api.platform_state import bootstrap_platform_state  # noqa: E402
from core.apps.dependencies import save_app_dependency_selection  # noqa: E402
from core.apps.service import install_store_app, register_app_source_from_contract  # noqa: E402
from core.providers.service import configure_workspace_provider  # noqa: E402
from core.workspaces.service import create_workspace, set_active_workspace_for_user  # noqa: E402
from opendesign_artifact import read_bundle_manifest, selected_asset, validate_bundle_manifest  # noqa: E402
from opendesign_bootstrap import bootstrap_empty_generation  # noqa: E402


WORKSPACES = ("default", "workspace-b")
APP_IDS = ("base-shell", "storage", "design-studio")
SETUP_MARKER = ".maverick-wp10-product-fixture.json"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
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
            "-o",
            str(output),
            str(source),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    output.chmod(0o755)
    return output


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


def _bootstrap_generation(root: Path, workspace_id: str) -> None:
    manifest = read_bundle_manifest(SERVICE_ROOT / "opendesign_bundle.json")
    validate_bundle_manifest(manifest, require_artifact_digest=True)
    asset = selected_asset(manifest, require_artifact_digest=True)
    generation_root = root / "workspaces" / workspace_id / "data" / "design-studio" / "opendesign"
    bootstrap_empty_generation(
        generation_root,
        artifact_sha256=asset["sha256"],
        opendesign_version=manifest["upstream"]["release_version"],
        verified_artifacts={asset["sha256"]: manifest["upstream"]["release_version"]},
    )


def _initial_setup(state, root: Path) -> None:
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
        _bootstrap_generation(root, workspace_id)
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
    state = bootstrap_platform_state(
        start_path=root,
        install_builtin_apps=False,
        register_builtin_provider_definitions=True,
    )
    if not (root / SETUP_MARKER).is_file():
        _initial_setup(state, root)
    start_backend_restart_recovery(state)
    app = PlatformAsgiHost(state)
    import uvicorn

    print(json.dumps({"ready": True, "port": arguments.port, "workspaces": list(WORKSPACES)}), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=arguments.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
