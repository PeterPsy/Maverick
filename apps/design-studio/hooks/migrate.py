"""Prepare native OpenDesign-owned and bounded Maverick-owned data roots.

The one-time legacy cutover is implemented by the explicit migration command;
this lifecycle hook never opens or mutates OpenDesign's private database.
"""

from __future__ import annotations

from pathlib import Path
import stat

from core.app_sdk.runtime import emit_json, read_entrypoint_payload


def main() -> None:
    payload = read_entrypoint_payload()
    prepared = []
    for name in ("opendesign-native", "delegations"):
        path = Path(payload.data_root) / name
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise SystemExit(f"Design Studio data path must be a real directory: {name}")
        path.chmod(0o700)
        prepared.append(name)
    emit_json({"ok": True, "schema_version": "3", "prepared": prepared})


if __name__ == "__main__":
    main()
