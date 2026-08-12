"""CLI entrypoint for Design Studio."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from core.app_sdk.runtime import emit_json, read_entrypoint_payload
from service import DesignStudioError, dispatch


def main() -> None:
    payload = read_entrypoint_payload()
    command_id = str(payload.raw.get("command_id") or "design-studio")
    arguments = dict(payload.arguments)
    action = str(arguments.pop("action", "") or _action_from_command(command_id))
    if action == "dev":
        service_root = Path(__file__).resolve().parents[1] / "service"
        sys.path.insert(0, str(service_root))
        from opendesign_dev_apply import DevApplyError, apply_incremental

        if str(arguments.pop("operation", "apply")) != "apply":
            emit_json({"ok": False, "error": "dev_operation_invalid", "detail": "Only dev apply is supported."})
            return
        try:
            emit_json({"ok": True, **apply_incremental(payload.raw, arguments)})
        except DevApplyError as error:
            emit_json(
                {
                    "ok": False,
                    "error": "dev_apply_failed",
                    "detail": str(error),
                    "report": error.report,
                }
            )
        return
    try:
        result = dispatch(action, payload.raw, arguments)
    except DesignStudioError as error:
        emit_json({"ok": False, "error": error.error, "detail": error.detail})
        return
    emit_json({"ok": True, **result})


def _action_from_command(command_id: str) -> str:
    if command_id == "design-studio":
        return "state"
    return command_id.rsplit(".", 1)[-1] or "state"


if __name__ == "__main__":
    main()
