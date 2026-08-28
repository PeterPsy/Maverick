"""Thin Design Studio backend; native product operations stay in OpenDesign."""

from __future__ import annotations

from pathlib import Path
import json
import stat
from typing import Any

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload


def main() -> None:
    payload = read_entrypoint_payload()
    action = str(payload.body.get("action") or "state")
    if action not in {"state", "status"}:
        emit_json(
            backend_response(
                404,
                {
                    "error": "unsupported_action",
                    "detail": "Native OpenDesign operations are not intercepted by Maverick.",
                },
            )
        )
        return
    emit_json(backend_response(200, _status(Path(payload.data_root))))


def _status(data_root: Path) -> dict[str, Any]:
    return {
        "mode": "official-native",
        "app_id": "design-studio",
        "native_data_owner": "opendesign",
        "host": _read_json(data_root / "native-host-status.json"),
        "bridges": _read_json(data_root / "bridge-capabilities.json"),
        "intercepts_native_routes": False,
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


if __name__ == "__main__":
    main()
