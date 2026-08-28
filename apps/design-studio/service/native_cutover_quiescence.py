"""Fail-closed native-host quiescence marker used during the one-time cutover."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from native_cutover_files import atomic_write_json, fsync_directory, real_directory
from native_cutover_state import (
    GENERATION_PATTERN,
    NativeDataCutoverError,
    cutover_lock,
    utc_now,
)


QUIESCE_FILE = "native-cutover-quiesce.json"
QUIESCE_FIELDS = {
    "schema_version",
    "kind",
    "cutover_id",
    "active",
    "created_at",
}


def quiesce_native_host(app_data_root: Path, *, cutover_id: str) -> dict[str, Any]:
    root = real_directory(app_data_root, label="Design Studio data root")
    if not GENERATION_PATTERN.fullmatch(cutover_id):
        raise NativeDataCutoverError("native cutover quiescence identity is invalid")
    with cutover_lock(root / ".native-cutover.lock"):
        path = root / QUIESCE_FILE
        if path.exists() or path.is_symlink():
            marker = read_quiescence(path)
            if marker["cutover_id"] != cutover_id:
                raise NativeDataCutoverError("another native cutover already owns quiescence")
            return marker
        marker = {
            "schema_version": "1",
            "kind": "design-studio-native-cutover-quiescence",
            "cutover_id": cutover_id,
            "active": True,
            "created_at": utc_now(),
        }
        atomic_write_json(path, marker)
        return marker


def release_native_host(app_data_root: Path, *, cutover_id: str) -> None:
    root = real_directory(app_data_root, label="Design Studio data root")
    with cutover_lock(root / ".native-cutover.lock"):
        path = root / QUIESCE_FILE
        marker = read_quiescence(path)
        if marker["cutover_id"] != cutover_id:
            raise NativeDataCutoverError("native cutover quiescence identity mismatch")
        path.unlink()
        fsync_directory(root)


def reject_if_native_host_quiesced(app_data_root: Path) -> None:
    path = app_data_root / QUIESCE_FILE
    if not path.exists() and not path.is_symlink():
        return
    read_quiescence(path)
    raise NativeDataCutoverError("native OpenDesign host is quiesced for certified data cutover")


def read_quiescence(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            raise NativeDataCutoverError("native cutover quiescence marker is unsafe")
        marker = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NativeDataCutoverError("native cutover quiescence marker is unreadable") from error
    if (
        not isinstance(marker, dict)
        or set(marker) != QUIESCE_FIELDS
        or marker.get("schema_version") != "1"
        or marker.get("kind") != "design-studio-native-cutover-quiescence"
        or marker.get("active") is not True
        or not isinstance(marker.get("cutover_id"), str)
        or not GENERATION_PATTERN.fullmatch(marker["cutover_id"])
        or not isinstance(marker.get("created_at"), str)
        or not marker["created_at"]
    ):
        raise NativeDataCutoverError("native cutover quiescence marker schema is invalid")
    return marker
