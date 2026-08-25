"""Uniform v2 content manifest for protected OpenDesign store entries."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

from opendesign_archive import (
    FILE_MANIFEST_PATH,
    MATERIALIZED_MARKER_PATH,
    artifact_paths,
    validate_symlink_target,
)
from opendesign_artifact import ArtifactError, safe_relative_path, sha256_file


STORE_MANIFEST_SCHEMA_VERSION = "2"


class StoreManifestError(ArtifactError):
    """Report bounded differences without leaking host paths."""

    def __init__(self, message: str, *, differences: int = 1) -> None:
        super().__init__(message)
        self.differences = max(1, differences)


def create_store_manifest(
    root: Path,
    *,
    verified_file_manifest: dict[str, Any] | None = None,
    verified_directory_entries: list[dict[str, Any]] | None = None,
    max_workers: int | None = None,
) -> dict[str, Any]:
    """Inventory files, executables, symlinks, directories, modes, and bytes."""
    root = _real_directory(root)
    if verified_file_manifest is not None and verified_directory_entries is not None:
        return _manifest_from_verified_inventory(
            root,
            verified_file_manifest=verified_file_manifest,
            verified_directory_entries=verified_directory_entries,
        )
    verified_entries = _verified_file_entries(verified_file_manifest)
    entries: list[dict[str, Any]] = []
    regular: list[tuple[Path, str, int]] = []
    for path in artifact_paths(root):
        relative = safe_relative_path(path.relative_to(root).as_posix())
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISLNK(metadata.st_mode):
            target = os.readlink(path)
            validate_symlink_target(relative, target)
            entry = {
                "path": relative,
                "kind": "symlink",
                "mode": f"{mode:04o}",
                "target": target,
                "sha256": hashlib.sha256(target.encode("utf-8")).hexdigest(),
            }
            trusted = verified_entries.pop(relative, None)
            if trusted is not None and trusted != entry:
                raise StoreManifestError("Preverified OpenDesign symlink metadata changed")
            entries.append(entry)
        elif stat.S_ISDIR(metadata.st_mode):
            entries.append({"path": relative, "kind": "directory", "mode": f"{mode:04o}"})
        elif stat.S_ISREG(metadata.st_mode):
            trusted = verified_entries.pop(relative, None)
            if trusted is None:
                regular.append((path, relative, mode))
            else:
                descriptor = {
                    "path": relative,
                    "kind": "file",
                    "mode": f"{mode:04o}",
                    "size_bytes": metadata.st_size,
                    "sha256": trusted["sha256"],
                }
                if descriptor != trusted:
                    raise StoreManifestError("Preverified OpenDesign file metadata changed")
                entries.append(descriptor)
        else:
            raise StoreManifestError("OpenDesign store contains an unsupported filesystem object")
    if regular:
        workers = min(_validated_worker_limit(max_workers), len(regular))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="od-store-audit") as executor:
            entries.extend(executor.map(_file_entry, regular))
    if verified_entries:
        raise StoreManifestError(
            "Preverified OpenDesign manifest contains missing filesystem entries",
            differences=len(verified_entries),
        )
    entries.sort(key=lambda item: str(item["path"]))
    file_count = sum(entry["kind"] == "file" for entry in entries)
    total_size = sum(int(entry.get("size_bytes", 0)) for entry in entries)
    return {
        "schema_version": STORE_MANIFEST_SCHEMA_VERSION,
        "file_count": file_count,
        "total_size_bytes": total_size,
        "entries": entries,
    }


def _manifest_from_verified_inventory(
    root: Path,
    *,
    verified_file_manifest: dict[str, Any],
    verified_directory_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    entries = list(_verified_file_entries(verified_file_manifest).values())
    if verified_file_manifest.get("self_excluded") != [FILE_MANIFEST_PATH]:
        raise StoreManifestError("Preverified OpenDesign manifest exclusions are not canonical")
    for entry in verified_directory_entries:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"path", "kind", "mode"}
            or entry.get("kind") != "directory"
        ):
            raise StoreManifestError("Preverified OpenDesign directory inventory is invalid")
        safe_relative_path(str(entry.get("path") or ""))
        mode = entry.get("mode")
        if not isinstance(mode, str) or len(mode) != 4 or any(char not in "01234567" for char in mode):
            raise StoreManifestError("Preverified OpenDesign directory mode is invalid")
        entries.append(dict(entry))
    for relative in (FILE_MANIFEST_PATH, MATERIALIZED_MARKER_PATH):
        path = root / relative
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise StoreManifestError("OpenDesign materialization metadata is invalid")
        entries.append(
            {
                "path": relative,
                "kind": "file",
                "mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
                "size_bytes": metadata.st_size,
                "sha256": sha256_file(path),
            }
        )
    entries.sort(key=lambda item: str(item["path"]))
    if len({str(entry["path"]) for entry in entries}) != len(entries):
        raise StoreManifestError("Preverified OpenDesign inventory contains duplicate paths")
    payload = {
        "schema_version": STORE_MANIFEST_SCHEMA_VERSION,
        "file_count": sum(entry["kind"] == "file" for entry in entries),
        "total_size_bytes": sum(int(entry.get("size_bytes", 0)) for entry in entries),
        "entries": entries,
    }
    return validate_store_manifest(payload)


def _verified_file_entries(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if payload is None:
        return {}
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "self_excluded", "files"}:
        raise StoreManifestError("Preverified OpenDesign file manifest schema is invalid")
    files = payload.get("files")
    excluded = payload.get("self_excluded")
    if (
        payload.get("schema_version") != "1"
        or not isinstance(files, list)
        or not isinstance(excluded, list)
        or any(not isinstance(item, str) for item in excluded)
    ):
        raise StoreManifestError("Preverified OpenDesign file manifest schema is invalid")
    validation = {
        "schema_version": STORE_MANIFEST_SCHEMA_VERSION,
        "file_count": sum(isinstance(entry, dict) and entry.get("kind") == "file" for entry in files),
        "total_size_bytes": sum(
            int(entry.get("size_bytes", 0))
            for entry in files
            if isinstance(entry, dict) and entry.get("kind") == "file"
        ),
        "entries": files,
    }
    validate_store_manifest(validation)
    return {str(entry["path"]): dict(entry) for entry in files}


def verify_store_manifest(
    root: Path,
    expected: dict[str, Any],
    *,
    max_workers: int | None = None,
) -> dict[str, Any]:
    """Perform the complete content/mode/extra-file audit."""
    validate_store_manifest(expected)
    actual = create_store_manifest(root, max_workers=max_workers)
    if actual == expected:
        return actual
    expected_entries = {entry["path"]: entry for entry in expected["entries"]}
    actual_entries = {entry["path"]: entry for entry in actual["entries"]}
    paths = set(expected_entries) | set(actual_entries)
    differences = sum(expected_entries.get(path) != actual_entries.get(path) for path in paths)
    raise StoreManifestError(
        "OpenDesign protected store content differs from manifest v2",
        differences=differences,
    )


def validate_store_manifest(payload: object) -> dict[str, Any]:
    """Validate the closed manifest-v2 schema without touching content."""
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "file_count",
        "total_size_bytes",
        "entries",
    }:
        raise StoreManifestError("OpenDesign store manifest v2 schema is invalid")
    if payload.get("schema_version") != STORE_MANIFEST_SCHEMA_VERSION:
        raise StoreManifestError("OpenDesign store manifest v2 version is unsupported")
    entries = payload.get("entries")
    if not isinstance(entries, list) or entries != sorted(entries, key=lambda item: str(item.get("path", ""))):
        raise StoreManifestError("OpenDesign store manifest v2 entries are invalid")
    seen: set[str] = set()
    calculated_files = 0
    calculated_size = 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise StoreManifestError("OpenDesign store manifest v2 entry is invalid")
        relative = safe_relative_path(str(entry.get("path") or ""))
        if relative in seen:
            raise StoreManifestError("OpenDesign store manifest v2 contains duplicate paths")
        seen.add(relative)
        kind = entry.get("kind")
        mode = entry.get("mode")
        if not isinstance(mode, str) or len(mode) != 4 or any(char not in "01234567" for char in mode):
            raise StoreManifestError("OpenDesign store manifest v2 mode is invalid")
        if kind == "directory":
            expected_fields = {"path", "kind", "mode"}
        elif kind == "symlink":
            expected_fields = {"path", "kind", "mode", "target", "sha256"}
            target = entry.get("target")
            if not isinstance(target, str):
                raise StoreManifestError("OpenDesign store manifest v2 symlink is invalid")
            validate_symlink_target(relative, target)
            if entry.get("sha256") != hashlib.sha256(target.encode("utf-8")).hexdigest():
                raise StoreManifestError("OpenDesign store manifest v2 symlink digest is invalid")
        elif kind == "file":
            expected_fields = {"path", "kind", "mode", "size_bytes", "sha256"}
            size = entry.get("size_bytes")
            digest = entry.get("sha256")
            if (
                isinstance(size, bool)
                or not isinstance(size, int)
                or size < 0
                or not isinstance(digest, str)
                or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
            ):
                raise StoreManifestError("OpenDesign store manifest v2 file descriptor is invalid")
            calculated_files += 1
            calculated_size += size
        else:
            raise StoreManifestError("OpenDesign store manifest v2 kind is invalid")
        if set(entry) != expected_fields:
            raise StoreManifestError("OpenDesign store manifest v2 entry fields are invalid")
    if payload.get("file_count") != calculated_files or payload.get("total_size_bytes") != calculated_size:
        raise StoreManifestError("OpenDesign store manifest v2 summary is invalid")
    return payload


def manifest_sha256(payload: dict[str, Any]) -> str:
    """Hash canonical manifest bytes without depending on file placement."""
    validate_store_manifest(payload)
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_entry(item: tuple[Path, str, int]) -> dict[str, Any]:
    path, relative, mode = item
    return {
        "path": relative,
        "kind": "file",
        "mode": f"{mode:04o}",
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _validated_worker_limit(value: int | None) -> int:
    if value is None:
        return 4
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 8:
        raise StoreManifestError("OpenDesign audit worker limit is invalid")
    return value


def _real_directory(path: Path) -> Path:
    path = Path(path)
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise StoreManifestError("OpenDesign store content is missing") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise StoreManifestError("OpenDesign store content must be a real directory")
    return path.resolve(strict=True)
