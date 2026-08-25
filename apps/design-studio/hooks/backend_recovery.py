"""Report pending app-owned OpenDesign activation recovery after a backend restart."""

from __future__ import annotations

from pathlib import Path
import sys

from core.apps.artifact_mounts import platform_artifact_store_root
from core.app_sdk.runtime import emit_json, read_entrypoint_payload

SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
REPOSITORY_ROOT = SERVICE_ROOT.parents[2]
sys.path.insert(0, str(SERVICE_ROOT))

from opendesign_artifact_store import OpenDesignArtifactStore  # noqa: E402
from opendesign_generation_control import load_generation_control_metadata  # noqa: E402
from opendesign_runtime import verified_overlay_from_store  # noqa: E402
from opendesign_runtime_activation import runtime_activation_recovery_state  # noqa: E402
from opendesign_web_activation import web_activation_recovery_state  # noqa: E402


def main() -> None:
    payload = read_entrypoint_payload()
    generation_root = Path(payload.data_root) / "opendesign"
    control_path = generation_root / "control.json"
    if not control_path.is_file() or control_path.is_symlink():
        emit_json({"ok": True, "web_activation_recovery": "not_required"})
        return
    control = load_generation_control_metadata(generation_root)
    store = OpenDesignArtifactStore(
        platform_artifact_store_root(REPOSITORY_ROOT) / "design-studio" / "opendesign"
    )
    selections = [control.active]
    if control.previous_web is not None:
        selections.append(control.previous_web)
    if control.previous_runtime is not None:
        selections.append(control.previous_runtime)
    artifacts: dict[str, str] = {}
    overlays = {}
    for selection in selections:
        runtime = store.fast_runtime(
            selection.runtime_artifact_sha256,
            file_manifest_sha256=None,
            opendesign_version=selection.od_version,
            upstream_commit=None,
        )
        artifacts[selection.runtime_artifact_sha256] = str(runtime.receipt["opendesign_version"])
        web = store.fast_web_overlay(
            selection.web_overlay_sha256,
            runtime_artifact_sha256=selection.runtime_artifact_sha256,
        )
        overlays[selection.web_overlay_sha256] = verified_overlay_from_store(web)
    if control.runtime_activation_id is not None:
        state = runtime_activation_recovery_state(
            generation_root,
            verified_artifacts=artifacts,
            verified_overlays=overlays,
        )
        recovery_key = "runtime_activation_recovery"
    else:
        state = web_activation_recovery_state(
            generation_root,
            verified_artifacts=artifacts,
            verified_overlays=overlays,
        )
        recovery_key = "web_activation_recovery"
    pending = state not in {None, "ready_committed", "rolled_back"}
    emit_json(
        {
            "ok": True,
            recovery_key: "pending" if pending else "not_required",
            "activation_state": state or "none",
        }
    )


if __name__ == "__main__":
    main()
