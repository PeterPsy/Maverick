"""Perform one governed, atomic repair of protected OpenDesign artifacts."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from opendesign_artifact_operations import run_artifact_operation  # noqa: E402
from opendesign_repair_state import failure_identity, write_repair_state  # noqa: E402


def main() -> None:
    payload = read_entrypoint_payload()
    data_root = Path(payload.data_root)
    write_repair_state(data_root, state="repairing")
    try:
        result = run_artifact_operation(
            "repair",
            data_root=data_root,
            workspace_id=str(payload.workspace_id or "default"),
            auto=True,
        )
    except Exception as error:
        code, phase = failure_identity(error)
        write_repair_state(
            data_root,
            state="failed",
            error_code=code,
            phase=phase,
        )
        raise
    write_repair_state(data_root, state="idle")
    emit_json({"ok": result.get("status") == "ready", "repair": result})


if __name__ == "__main__":
    main()
