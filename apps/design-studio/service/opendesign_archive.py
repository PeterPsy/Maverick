"""Deterministic OpenDesign archives, file manifests, and path safety."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile
from typing import Any
from uuid import uuid4

from opendesign_artifact import (
    ArtifactError,
    is_sha256,
    reject_duplicate_pairs,
    safe_relative_path,
    sha256_file,
)


FILE_MANIFEST_PATH = "maverick/manifest.json"
MATERIALIZED_MARKER_PATH = "maverick/materialized.json"
MATERIALIZED_MARKER_SCHEMA_VERSION = "2"


def create_file_manifest(root: Path, *, exclude: set[str] | None = None) -> dict[str, Any]:
    excluded = set(exclude or set())
    entries: list[dict[str, Any]] = []
    regular_files: list[tuple[Path, str, int]] = []
    for path in artifact_paths(root):
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        mode = stat.S_IMODE(path.lstat().st_mode)
        if path.is_symlink():
            target = os.readlink(path)
            validate_symlink_target(relative, target)
            entries.append(
                {
                    "path": relative,
                    "kind": "symlink",
                    "mode": f"{mode:04o}",
                    "target": target,
                    "sha256": hashlib.sha256(target.encode("utf-8")).hexdigest(),
                }
            )
        elif path.is_dir():
            continue
        elif path.is_file():
            regular_files.append((path, relative, mode))
        else:
            raise ArtifactError(f"Unsupported artifact filesystem object: {relative}")
    if regular_files:
        worker_count = min(4, len(regular_files))
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="od-verify") as executor:
            entries.extend(executor.map(_regular_file_manifest_entry, regular_files))
    entries.sort(key=lambda entry: str(entry["path"]))
    return {"schema_version": "1", "self_excluded": sorted(excluded), "files": entries}


def _regular_file_manifest_entry(item: tuple[Path, str, int]) -> dict[str, Any]:
    path, relative, mode = item
    return {
        "path": relative,
        "kind": "file",
        "mode": f"{mode:04o}",
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_deterministic_archive(root: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.GNU_FORMAT) as archive:
                    for path in artifact_paths(root):
                        relative = path.relative_to(root).as_posix()
                        info = archive.gettarinfo(str(path), arcname=relative)
                        info.uid = 0
                        info.gid = 0
                        info.uname = "root"
                        info.gname = "root"
                        info.mtime = 0
                        if info.isfile():
                            with path.open("rb") as handle:
                                archive.addfile(info, handle)
                        else:
                            archive.addfile(info)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def validated_archive_members(bundle: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = bundle.getmembers()
    seen: set[str] = set()
    for member in members:
        relative = validate_archive_member(member)
        if relative in seen:
            raise ArtifactError(f"Duplicate OpenDesign archive member: {relative}")
        seen.add(relative)
    return members


def verify_file_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / FILE_MANIFEST_PATH
    try:
        expected = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ArtifactError("OpenDesign file manifest is missing or invalid") from exc
    if not isinstance(expected, dict) or set(expected) != {"schema_version", "self_excluded", "files"}:
        raise ArtifactError("OpenDesign file manifest schema is invalid")
    excluded_value = expected.get("self_excluded")
    if not isinstance(excluded_value, list) or not all(isinstance(item, str) for item in excluded_value):
        raise ArtifactError("OpenDesign file manifest exclusions are invalid")
    excluded = set(excluded_value)
    actual = create_file_manifest(root, exclude=excluded | {MATERIALIZED_MARKER_PATH})
    actual["self_excluded"] = sorted(excluded)
    if actual != expected:
        raise ArtifactError("OpenDesign materialized file manifest mismatch")
    return expected


def verify_materialized_bundle(
    root: Path,
    *,
    expected_artifact_sha256: str,
    expected_file_manifest_sha256: str,
    expected_version: str,
) -> dict[str, Any]:
    if not is_sha256(expected_artifact_sha256) or not is_sha256(expected_file_manifest_sha256):
        raise ArtifactError("Pinned OpenDesign materialization digests are invalid")
    if (
        not isinstance(expected_version, str)
        or not expected_version.strip()
        or expected_version.strip() != expected_version
    ):
        raise ArtifactError("Pinned OpenDesign materialization version is invalid")
    if root.is_symlink() or not root.is_dir():
        raise ArtifactError("Materialized OpenDesign root must be a real directory")
    marker = read_materialized_marker(root)
    if marker.get("artifact_sha256") != expected_artifact_sha256:
        raise ArtifactError("Materialized OpenDesign artifact digest does not match the pin")
    if marker.get("opendesign_version") != expected_version:
        raise ArtifactError("Materialized OpenDesign version does not match the pin")
    manifest_sha256 = sha256_file(root / FILE_MANIFEST_PATH)
    if marker.get("file_manifest_sha256") != manifest_sha256:
        raise ArtifactError("Materialized OpenDesign file manifest marker mismatch")
    if manifest_sha256 != expected_file_manifest_sha256:
        raise ArtifactError("Materialized OpenDesign file manifest digest does not match the pin")
    verify_file_manifest(root)
    return marker


def read_materialized_marker(root: Path) -> dict[str, Any]:
    try:
        marker = json.loads(
            (root / MATERIALIZED_MARKER_PATH).read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ArtifactError("Materialized OpenDesign artifact marker is missing or invalid") from exc
    if not isinstance(marker, dict) or set(marker) != {
        "schema_version",
        "artifact_sha256",
        "file_manifest_sha256",
        "opendesign_version",
        "upstream_commit",
    }:
        raise ArtifactError("Materialized OpenDesign artifact marker schema is invalid")
    if marker.get("schema_version") != MATERIALIZED_MARKER_SCHEMA_VERSION:
        raise ArtifactError("Materialized OpenDesign artifact marker version is unsupported")
    if not is_sha256(marker.get("artifact_sha256")) or not is_sha256(marker.get("file_manifest_sha256")):
        raise ArtifactError("Materialized OpenDesign artifact marker digests are invalid")
    version = marker.get("opendesign_version")
    if not isinstance(version, str) or not version.strip() or version.strip() != version:
        raise ArtifactError("Materialized OpenDesign artifact marker version is invalid")
    commit = marker.get("upstream_commit")
    if (
        not isinstance(commit, str)
        or len(commit) != 40
        or commit.lower() != commit
        or any(character not in "0123456789abcdef" for character in commit)
    ):
        raise ArtifactError("Materialized OpenDesign artifact marker commit is invalid")
    return marker


def artifact_paths(root: Path) -> list[Path]:
    if root.is_symlink() or not root.is_dir():
        raise ArtifactError("OpenDesign staging root must be a real directory")
    paths: list[Path] = []
    for current_root, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(current_root)
        directories.sort()
        filenames.sort()
        paths.extend(current / name for name in directories)
        paths.extend(current / name for name in filenames)
    return sorted(paths, key=lambda item: item.relative_to(root).as_posix())


def validate_archive_member(member: tarfile.TarInfo) -> str:
    relative = safe_relative_path(member.name)
    if member.isdev() or member.isfifo() or member.islnk():
        raise ArtifactError(f"Unsupported OpenDesign archive member: {relative}")
    if member.issym():
        validate_symlink_target(relative, member.linkname)
    elif not (member.isfile() or member.isdir()):
        raise ArtifactError(f"Unsupported OpenDesign archive member type: {relative}")
    return relative


def validate_symlink_target(relative: str, target: str) -> None:
    if not target or "\\" in target:
        raise ArtifactError(f"OpenDesign artifact symlink {relative} has an invalid target")
    target_path = PurePosixPath(target)
    if target_path.is_absolute():
        raise ArtifactError(f"OpenDesign artifact symlink {relative} is absolute")
    resolved_parts: list[str] = []
    for part in PurePosixPath(relative).parent.joinpath(target_path).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not resolved_parts:
                raise ArtifactError(f"OpenDesign artifact symlink {relative} escapes the artifact")
            resolved_parts.pop()
        else:
            resolved_parts.append(part)
