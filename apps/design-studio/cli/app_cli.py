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

        operation = str(arguments.pop("operation", "apply"))
        if operation == "benchmark":
            from benchmark_opendesign_change_to_live import (
                ChangeToLiveBenchmarkError,
                run_change_to_live_benchmark,
            )

            try:
                emit_json(
                    {
                        "status_code": 200,
                        "ok": True,
                        **run_change_to_live_benchmark(payload.raw, arguments),
                    }
                )
            except (ChangeToLiveBenchmarkError, DevApplyError) as error:
                emit_json(
                    {
                        "status_code": 500,
                        "ok": False,
                        "error": "change_to_live_benchmark_failed",
                        "detail": str(error),
                    }
                )
            return
        if operation != "apply":
            emit_json(
                {
                    "status_code": 400,
                    "ok": False,
                    "error": "dev_operation_invalid",
                    "detail": "Only dev apply and dev benchmark are supported.",
                }
            )
            return
        try:
            emit_json({"status_code": 200, "ok": True, **apply_incremental(payload.raw, arguments)})
        except DevApplyError as error:
            emit_json(
                {
                    "status_code": 500,
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
        emit_json({"status_code": 400, "ok": False, "error": error.error, "detail": error.detail})
        return
    emit_json({"status_code": 200, "ok": True, **result})


def _action_from_command(command_id: str) -> str:
    if command_id == "design-studio":
        return "state"
    return command_id.rsplit(".", 1)[-1] or "state"


if __name__ == "__main__":
    main()
