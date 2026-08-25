"""Recoverable filesystem snapshots for continuation-repair operations."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil

from core.recovery.continuation_provider_snapshot import (
    resolve_snapshot_lineage_session_ids,
    snapshot_provider_conversation_homes,
)
from core.runtime.paths import runtime_session_root, workspace_runtime_root


def snapshot_runtime_continuation_state(
    repository_root: Path,
    *,
    workspace_id: str,
    session_ids: set[str],
    now: datetime | None = None,
) -> dict[str, object]:
    """Copy every persisted record that a scoped continuation repair can mutate."""
    normalized_session_ids = sorted(
        {str(session_id or "").strip() for session_id in session_ids}
        - {""}
    )
    if not normalized_session_ids:
        raise RuntimeError("runtime_continuation_snapshot_scope_empty")
    lineage_session_ids = resolve_snapshot_lineage_session_ids(
        repository_root,
        workspace_id=workspace_id,
        session_ids=normalized_session_ids,
    )
    timestamp = now or datetime.now(tz=UTC)
    snapshot_id = timestamp.strftime("continuation-%Y%m%dT%H%M%S%fZ")
    destination = repository_root / "data" / "recovery-snapshots" / snapshot_id
    provider_root = repository_root / "data" / "control-plane" / "json" / "providers"
    runtime_root = workspace_runtime_root(
        workspace_id=workspace_id,
        start_path=repository_root,
    )
    provider_paths = (
        sorted(provider_root.rglob("*.json")) if provider_root.is_dir() else []
    )
    runtime_paths = _scoped_runtime_json_paths(
        repository_root,
        workspace_id=workspace_id,
        session_ids=lineage_session_ids,
    )
    if not provider_paths or not runtime_paths:
        raise RuntimeError("runtime_continuation_snapshot_sources_missing")
    resolved_repository_root = repository_root.resolve(strict=True)
    for source in (provider_root, runtime_root):
        _require_snapshot_path(source, root=resolved_repository_root)
    resolved_destination = destination.resolve(strict=False)
    try:
        resolved_destination.relative_to(resolved_repository_root)
    except ValueError as error:
        raise RuntimeError("runtime_continuation_snapshot_path_escape") from error
    sources = (
        (
            "provider_control_plane",
            provider_root,
            provider_paths,
        ),
        (
            "workspace_runtime",
            runtime_root,
            runtime_paths,
        ),
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(mode=0o700, exist_ok=False)
    destination.chmod(0o700)
    copied: list[dict[str, object]] = []
    total_size_bytes = 0
    for label, source, paths in sources:
        target = destination / label
        for path in sorted(paths):
            if path.is_dir() or not path.exists() or path.name.endswith(".lock"):
                continue
            relative = path.relative_to(source)
            target_path = target / relative
            target_path.parent.mkdir(parents=True, exist_ok=True)
            _make_directory_tree_private(target_path.parent, stop=destination)
            if path.is_symlink():
                link_target = _safe_snapshot_symlink_target(path, source=source)
                target_path.symlink_to(link_target)
                content = link_target.encode("utf-8")
                size_bytes = len(content)
            elif path.is_file():
                _require_snapshot_path(path, root=source.resolve(strict=True))
                shutil.copy2(path, target_path)
                target_path.chmod(0o600)
                content = None
                size_bytes = target_path.stat().st_size
            else:
                continue
            copied.append(
                {
                    "source": str(path.relative_to(repository_root)),
                    "snapshot": str(target_path.relative_to(repository_root)),
                    "sha256": (
                        hashlib.sha256(content).hexdigest()
                        if content is not None
                        else _sha256_file(target_path)
                    ),
                    "size_bytes": size_bytes,
                    "symlink": path.is_symlink(),
                }
            )
            total_size_bytes += size_bytes
    provider_files = snapshot_provider_conversation_homes(
        repository_root,
        workspace_id=workspace_id,
        lineage_session_ids=lineage_session_ids,
        destination=destination,
    )
    copied.extend(provider_files)
    total_size_bytes += sum(int(item["size_bytes"]) for item in provider_files)
    if not copied:
        raise RuntimeError("runtime_continuation_snapshot_files_missing")
    manifest = {
        "schema_version": "2",
        "snapshot_id": snapshot_id,
        "workspace_id": workspace_id,
        "session_ids": normalized_session_ids,
        "lineage_session_ids": lineage_session_ids,
        "created_at": timestamp.isoformat(),
        "files": copied,
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_path.chmod(0o600)
    return {
        "snapshot_id": snapshot_id,
        "workspace_relative_path": str(destination.relative_to(repository_root)),
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "file_count": len(copied),
        "size_bytes": total_size_bytes,
    }


def _scoped_runtime_json_paths(
    repository_root: Path,
    *,
    workspace_id: str,
    session_ids: list[str],
) -> list[Path]:
    runtime_root = workspace_runtime_root(
        workspace_id=workspace_id,
        start_path=repository_root,
    )
    paths = set(runtime_root.glob("*.json"))
    for session_id in session_ids:
        session_root = runtime_session_root(
            workspace_id=workspace_id,
            session_id=session_id,
            start_path=repository_root,
        )
        paths.update(session_root.glob("*.json"))
        paths.update((session_root / "events-history").glob("*.json"))
    return sorted(paths)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _make_directory_tree_private(path: Path, *, stop: Path) -> None:
    current = path
    while True:
        current.chmod(0o700)
        if current == stop:
            return
        if stop not in current.parents:
            raise RuntimeError("runtime_continuation_snapshot_path_escape")
        current = current.parent


def _safe_snapshot_symlink_target(path: Path, *, source: Path) -> str:
    link_target = os.readlink(path)
    if Path(link_target).is_absolute():
        raise RuntimeError("runtime_continuation_snapshot_source_unsafe")
    _require_snapshot_path(path, root=source.resolve(strict=True))
    return link_target


def _require_snapshot_path(path: Path, *, root: Path) -> None:
    try:
        path.resolve(strict=True).relative_to(root)
    except (OSError, RuntimeError, ValueError) as error:
        raise RuntimeError("runtime_continuation_snapshot_source_unsafe") from error
