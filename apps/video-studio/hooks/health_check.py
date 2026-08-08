"""Verify the installed Video Studio database without exposing host paths."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from foundation.database import FoundationDatabase, FoundationDatabaseError


def main() -> None:
    payload = read_entrypoint_payload()
    try:
        result = FoundationDatabase(payload.data_root).health()
    except FoundationDatabaseError as error:
        raise SystemExit(str(error)) from error
    emit_json({"ok": True, **result})


if __name__ == "__main__":
    main()
