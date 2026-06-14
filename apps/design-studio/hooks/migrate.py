"""Migration hook for Design Studio."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from core.app_sdk.runtime import emit_json, read_entrypoint_payload
from store import ensure_state


def main() -> None:
    payload = read_entrypoint_payload()
    ensure_state(payload.data_root)
    emit_json({"ok": True})


if __name__ == "__main__":
    main()
