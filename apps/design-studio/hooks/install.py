"""Install hook for Design Studio."""

from __future__ import annotations

from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from core.app_sdk.runtime import emit_json, read_entrypoint_payload
from store import ensure_state


def main() -> None:
    payload = read_entrypoint_payload()
    ensure_state(payload.data_root)
    result = {"ok": True}
    if _declares_protected_store():
        service_root = Path(__file__).resolve().parents[1] / "service"
        sys.path.insert(0, str(service_root))
        from opendesign_artifact_operations import run_artifact_operation

        provisioned = run_artifact_operation(
            "provision",
            data_root=Path(payload.data_root),
            workspace_id=str(payload.workspace_id or "default"),
        )
        result["artifact_store"] = {
            "status": provisioned["status"],
            "store_generation": provisioned["store_generation"],
            "runtime_artifact_sha256": provisioned["runtime_artifact_sha256"],
            "retained_runtime_artifacts": provisioned["retained_runtime_artifacts"],
            "web_overlay_sha256": provisioned["web_overlay_sha256"],
            "retained_web_overlays": provisioned["retained_web_overlays"],
        }
    emit_json(result)


def _declares_protected_store() -> bool:
    contract_path = Path(__file__).resolve().parents[1] / "app_contract.json"
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        sidecars = contract["services"]["http_sidecars"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return False
    return any(sidecar.get("artifact_mounts") for sidecar in sidecars if isinstance(sidecar, dict))


if __name__ == "__main__":
    main()
