"""Legacy Design Studio catalog adapter for governed OpenDesign APIs."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

from opendesign_migration_files import (
    canonical_json,
    fsync_directory,
    read_bounded_regular_file,
    sha256_bytes,
)
from opendesign_migration_runtime import MigrationError, MigrationRuntime


LEGACY_PROJECT_MAP = "legacy-project-map.json"
MAX_LEGACY_STATE_BYTES = 8 * 1024 * 1024
MAX_LEGACY_IMPORT_BYTES = 10 * 1024 * 1024
_LEGACY_ID = re.compile(r"^design_[a-f0-9]{12}$")
_OD_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._~-]{0,127}$")


def read_legacy_state(path: Path, *, migration_root: Path) -> tuple[dict[str, object], str]:
    raw = read_bounded_regular_file(
        path,
        root=migration_root.parent,
        max_bytes=MAX_LEGACY_STATE_BYTES,
    )
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MigrationError("legacy state is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise MigrationError("legacy state must contain an object")
    return payload, sha256_bytes(raw)


def migrate_legacy_catalog(
    state: dict[str, object],
    *,
    migration_root: Path,
    runtime: MigrationRuntime,
    migration_id: str,
) -> tuple[list[dict[str, object]], int, int]:
    projects = state.get("projects")
    if not isinstance(projects, list):
        raise MigrationError("legacy state projects must be a list")
    mappings: list[dict[str, object]] = []
    import_count = 0
    for raw_project in projects:
        if not isinstance(raw_project, dict):
            raise MigrationError("legacy project must be an object")
        legacy_id = str(raw_project.get("id") or "")
        if not _LEGACY_ID.fullmatch(legacy_id):
            raise MigrationError("legacy project id is invalid")
        project_sha256 = sha256_bytes(canonical_json(raw_project))
        idempotency_key = sha256_bytes(f"{migration_id}:{legacy_id}".encode("utf-8"))
        od_project_id = runtime.create_legacy_project(raw_project, idempotency_key=idempotency_key)
        if not _OD_ID.fullmatch(od_project_id):
            raise MigrationError("OpenDesign returned an invalid project id")
        imported, migrated_count = _migrate_project_imports(
            raw_project,
            od_project_id=od_project_id,
            migration_root=migration_root,
            runtime=runtime,
        )
        import_count += migrated_count
        mappings.append(
            {
                "legacy_project_id": legacy_id,
                "od_project_id": od_project_id,
                "source_sha256": project_sha256,
                "imports": imported,
            }
        )
    return mappings, len(mappings), import_count


def seal_legacy_state(path: Path, *, migration_root: Path) -> None:
    read_bounded_regular_file(
        path,
        root=migration_root.parent,
        max_bytes=MAX_LEGACY_STATE_BYTES,
    )
    path.chmod(stat.S_IRUSR)
    with path.open("rb") as handle:
        os.fsync(handle.fileno())
    fsync_directory(path.parent)


def _migrate_project_imports(
    project: dict[str, object],
    *,
    od_project_id: str,
    migration_root: Path,
    runtime: MigrationRuntime,
) -> tuple[list[dict[str, object]], int]:
    raw_imports = project.get("imports", [])
    if not isinstance(raw_imports, list):
        raise MigrationError("legacy project imports must be a list")
    imported: list[dict[str, object]] = []
    for raw_import in raw_imports:
        if not isinstance(raw_import, dict) or raw_import.get("status") != "imported":
            continue
        relative = _safe_relative(raw_import.get("app_data_path"), label="legacy import app_data_path")
        source = migration_root.parent / PurePosixPath(relative)
        content = read_bounded_regular_file(
            source,
            root=migration_root.parent,
            max_bytes=MAX_LEGACY_IMPORT_BYTES,
        )
        name = Path(str(raw_import.get("name") or source.name)).name
        if not name or name in {".", ".."}:
            raise MigrationError("legacy import name is invalid")
        digest = sha256_bytes(content)
        runtime.upload_legacy_import(
            od_project_id,
            name=name,
            media_type=str(raw_import.get("media_type") or "application/octet-stream"),
            content=content,
            sha256=digest,
        )
        imported.append({"name": name, "sha256": digest, "size_bytes": len(content)})
    return imported, len(imported)


def _safe_relative(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise MigrationError(f"{label} is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise MigrationError(f"{label} is invalid")
    return value


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MigrationError(f"duplicate JSON field: {key}")
        result[key] = value
    return result
