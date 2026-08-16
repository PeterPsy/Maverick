"""Finalize app-owned OpenDesign activation recovery after a backend restart."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from opendesign_materialization import discover_verified_bundles  # noqa: E402
from opendesign_web_activation import finalize_web_activation_after_host_restart  # noqa: E402
from opendesign_web_overlay import discover_verified_overlays  # noqa: E402


def main() -> None:
    payload = read_entrypoint_payload()
    generation_root = Path(payload.data_root) / "opendesign"
    control_path = generation_root / "control.json"
    if not control_path.is_file() or control_path.is_symlink():
        emit_json({"ok": True, "web_activation_recovery": "not_required"})
        return
    bundles = discover_verified_bundles(SERVICE_ROOT / "vendor/open-design")
    artifacts = {digest: bundle.opendesign_version for digest, bundle in bundles.items()}
    overlays = discover_verified_overlays(
        SERVICE_ROOT / "vendor/open-design-web",
        trust_contract=SERVICE_ROOT / "opendesign_web_trust.json",
    )
    outcome = finalize_web_activation_after_host_restart(
        generation_root,
        verified_artifacts=artifacts,
        verified_overlays=overlays,
    )
    emit_json(
        {
            "ok": True,
            "web_activation_recovery": "not_required" if outcome is None else "completed",
            "rolled_back": bool(outcome and outcome.rolled_back),
        }
    )


if __name__ == "__main__":
    main()
