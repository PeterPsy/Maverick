"""Workspace-scoped selection of one verified official OpenDesign release."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import stat
from typing import Any

from native_cutover_files import atomic_write_json, real_directory
from official_oci_validation import reject_duplicate_pairs
from official_opendesign_release import (
    OfficialRelease,
    OfficialReleaseError,
    load_official_release_payload,
)


SELECTION_FILE = "official-release-selection.json"
SELECTION_FIELDS = {
    "schema_version",
    "kind",
    "selected_at",
    "descriptor_sha256",
    "release",
}


@dataclass(frozen=True)
class OfficialReleaseSelection:
    release: OfficialRelease
    selected_at: str
    descriptor_sha256: str
    payload: dict[str, Any]


def ensure_release_selection(app_data_root: Path, release: OfficialRelease) -> OfficialReleaseSelection:
    """Seed the bundled release once; never overwrite a user's later choice."""
    root = real_directory(app_data_root, label="Design Studio data root", create=True)
    path = root / SELECTION_FILE
    if path.exists() or path.is_symlink():
        return read_release_selection(root)
    write_release_selection(root, release)
    return read_release_selection(root)


def write_release_selection(
    app_data_root: Path,
    release: OfficialRelease,
    *,
    selected_at: str | None = None,
) -> OfficialReleaseSelection:
    """Atomically select a previously verified official package identity."""
    root = real_directory(app_data_root, label="Design Studio data root", create=True)
    descriptor = release.descriptor()
    payload = {
        "schema_version": "1",
        "kind": "design-studio-official-release-selection",
        "selected_at": selected_at or _utc_now(),
        "descriptor_sha256": descriptor_sha256(descriptor),
        "release": descriptor,
    }
    atomic_write_json(root / SELECTION_FILE, payload)
    return read_release_selection(root)


def read_release_selection(app_data_root: Path) -> OfficialReleaseSelection:
    """Read and fully revalidate the selected official descriptor."""
    root = real_directory(app_data_root, label="Design Studio data root")
    path = root / SELECTION_FILE
    try:
        metadata = path.lstat()
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise OfficialReleaseError("official OpenDesign release selection is unreadable") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise OfficialReleaseError("official OpenDesign release selection is unsafe")
    if (
        not isinstance(payload, dict)
        or set(payload) != SELECTION_FIELDS
        or payload.get("schema_version") != "1"
        or payload.get("kind") != "design-studio-official-release-selection"
        or not isinstance(payload.get("selected_at"), str)
        or not payload["selected_at"]
        or not isinstance(payload.get("release"), dict)
    ):
        raise OfficialReleaseError("official OpenDesign release selection schema is invalid")
    expected_sha = descriptor_sha256(payload["release"])
    if payload.get("descriptor_sha256") != expected_sha:
        raise OfficialReleaseError("official OpenDesign release selection digest is invalid")
    release = load_official_release_payload(payload["release"], require_bundled_pin=False)
    return OfficialReleaseSelection(
        release=release,
        selected_at=payload["selected_at"],
        descriptor_sha256=expected_sha,
        payload=payload,
    )


def descriptor_sha256(payload: object) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "SELECTION_FILE",
    "OfficialReleaseSelection",
    "descriptor_sha256",
    "ensure_release_selection",
    "read_release_selection",
    "write_release_selection",
]
