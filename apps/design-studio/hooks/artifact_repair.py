"""Perform one governed, atomic repair of protected OpenDesign artifacts."""

from __future__ import annotations

from pathlib import Path
import sys
import time

from core.app_sdk.runtime import emit_json, read_entrypoint_payload


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from opendesign_artifact_operations import run_artifact_operation  # noqa: E402
from opendesign_artifact import write_canonical_json  # noqa: E402


def main() -> None:
    payload = read_entrypoint_payload()
    data_root = Path(payload.data_root)
    state_path = data_root / "opendesign" / "repair-state.json"
    started_at = int(time.time() * 1000)
    _write_state(state_path, state="repairing", observed_at=started_at)
    try:
        result = run_artifact_operation(
            "repair",
            data_root=data_root,
            workspace_id=str(payload.workspace_id or "default"),
            auto=True,
        )
    except Exception as error:
        _write_state(
            state_path,
            state="failed",
            observed_at=int(time.time() * 1000),
            error_code=getattr(error, "code", "artifact_repair_failed"),
            phase=getattr(error, "phase", "artifact_repair"),
        )
        raise
    _write_state(state_path, state="idle", observed_at=int(time.time() * 1000))
    emit_json({"ok": result.get("status") == "ready", "repair": result})


def _write_state(
    path: Path,
    *,
    state: str,
    observed_at: int,
    error_code: str | None = None,
    phase: str | None = None,
) -> None:
    write_canonical_json(
        path,
        {
            "schema_version": "1",
            "state": state,
            "observed_at_epoch_ms": observed_at,
            "error_code": error_code,
            "phase": phase,
        },
    )


if __name__ == "__main__":
    main()
