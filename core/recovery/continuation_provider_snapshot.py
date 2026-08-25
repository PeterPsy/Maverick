"""Consistent provider-conversation backups for continuation repair."""

from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from urllib.parse import quote

from core.runtime.paths import runtime_session_root, workspace_runtime_root


MAX_PROVIDER_SNAPSHOT_BYTES = 2 * 1024 * 1024 * 1024
_LINEAGE_ID_FIELDS = (
    "predecessor_session_id",
    "continuation_successor_session_id",
    "lineage_root_session_id",
)


def resolve_snapshot_lineage_session_ids(
    repository_root: Path,
    *,
    workspace_id: str,
    session_ids: list[str],
) -> list[str]:
    """Expand selected sessions to every persisted member of their lineage."""
    pending = list(session_ids)
    resolved: set[str] = set()
    handoff_links = _continuation_handoff_links(
        repository_root,
        workspace_id=workspace_id,
    )
    while pending:
        session_id = pending.pop()
        if session_id in resolved:
            continue
        session_root = _canonical_session_root(
            repository_root,
            workspace_id=workspace_id,
            session_id=session_id,
        )
        document = _read_session_document(
            session_root / "session.json",
            session_id=session_id,
        )
        resolved.add(session_id)
        for field_name in _LINEAGE_ID_FIELDS:
            related_id = str(document.get(field_name) or "").strip()
            if related_id and related_id not in resolved:
                pending.append(related_id)
        for related_id in handoff_links.get(session_id, ()):
            related_document = runtime_session_root(
                workspace_id=workspace_id,
                session_id=related_id,
                start_path=repository_root,
            ) / "session.json"
            if related_id not in resolved and related_document.is_file():
                pending.append(related_id)
        if len(resolved) > 1000:
            raise RuntimeError("runtime_continuation_snapshot_lineage_too_large")
    return sorted(resolved)


def _continuation_handoff_links(
    repository_root: Path,
    *,
    workspace_id: str,
) -> dict[str, set[str]]:
    path = workspace_runtime_root(
        workspace_id=workspace_id,
        start_path=repository_root,
    ) / "continuation_handoffs.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError("runtime_continuation_snapshot_handoff_invalid") from error
    if not isinstance(payload, list) or any(
        not isinstance(item, dict) for item in payload
    ):
        raise RuntimeError("runtime_continuation_snapshot_handoff_invalid")
    links: dict[str, set[str]] = {}
    for item in payload:
        predecessor_id = str(item.get("predecessor_session_id") or "").strip()
        successor_id = str(item.get("successor_session_id") or "").strip()
        if not predecessor_id or not successor_id:
            raise RuntimeError("runtime_continuation_snapshot_handoff_invalid")
        links.setdefault(predecessor_id, set()).add(successor_id)
        links.setdefault(successor_id, set()).add(predecessor_id)
    return links


def snapshot_provider_conversation_homes(
    repository_root: Path,
    *,
    workspace_id: str,
    lineage_session_ids: list[str],
    destination: Path,
) -> list[dict[str, object]]:
    """Back up canonical lineage-root SQLite stores and rollout archives."""
    root_session_ids = _lineage_root_session_ids(
        repository_root,
        workspace_id=workspace_id,
        session_ids=lineage_session_ids,
    )
    copied: list[dict[str, object]] = []
    total_size = 0
    codex_root_session_ids = _codex_lineage_root_session_ids(
        repository_root,
        workspace_id=workspace_id,
        session_ids=lineage_session_ids,
    )
    for root_session_id in root_session_ids:
        session_root = _canonical_session_root(
            repository_root,
            workspace_id=workspace_id,
            session_id=root_session_id,
        )
        codex_home = session_root / "codex-home"
        if codex_home.is_symlink():
            raise RuntimeError("runtime_continuation_snapshot_provider_home_unsafe")
        if not codex_home.is_dir():
            if root_session_id in codex_root_session_ids:
                raise RuntimeError(
                    "runtime_continuation_snapshot_provider_home_missing"
                )
            continue
        if codex_home.resolve(strict=True).parent != session_root:
            raise RuntimeError("runtime_continuation_snapshot_provider_home_unsafe")
        paths = _provider_conversation_paths(codex_home)
        if root_session_id in codex_root_session_ids:
            if not any(path.suffix == ".sqlite" for path in paths):
                raise RuntimeError(
                    "runtime_continuation_snapshot_provider_database_missing"
                )
            if not any(path.suffix == ".jsonl" for path in paths):
                raise RuntimeError(
                    "runtime_continuation_snapshot_provider_rollout_missing"
                )
        for source in paths:
            source_size = source.stat().st_size
            if total_size + source_size > MAX_PROVIDER_SNAPSHOT_BYTES:
                raise RuntimeError("runtime_continuation_snapshot_provider_home_too_large")
            relative = source.relative_to(codex_home)
            target = (
                destination
                / "provider_conversation_homes"
                / root_session_id
                / "codex-home"
                / relative
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            _make_private_tree(target.parent, stop=destination)
            if source.suffix == ".sqlite":
                _backup_sqlite(source, target)
                kind = "sqlite_backup"
            else:
                shutil.copy2(source, target)
                target.chmod(0o600)
                kind = "rollout"
            size_bytes = target.stat().st_size
            total_size += size_bytes
            if total_size > MAX_PROVIDER_SNAPSHOT_BYTES:
                raise RuntimeError("runtime_continuation_snapshot_provider_home_too_large")
            copied.append(
                {
                    "source": str(source.relative_to(repository_root)),
                    "snapshot": str(target.relative_to(repository_root)),
                    "sha256": _sha256_file(target),
                    "size_bytes": size_bytes,
                    "symlink": False,
                    "kind": kind,
                    "lineage_root_session_id": root_session_id,
                }
            )
    return copied


def _lineage_root_session_ids(
    repository_root: Path,
    *,
    workspace_id: str,
    session_ids: list[str],
) -> list[str]:
    roots: set[str] = set()
    for session_id in session_ids:
        session_root = _canonical_session_root(
            repository_root,
            workspace_id=workspace_id,
            session_id=session_id,
        )
        document = _read_session_document(
            session_root / "session.json",
            session_id=session_id,
        )
        roots.add(str(document.get("lineage_root_session_id") or session_id).strip())
    return sorted(roots)


def _codex_lineage_root_session_ids(
    repository_root: Path,
    *,
    workspace_id: str,
    session_ids: list[str],
) -> set[str]:
    roots: set[str] = set()
    for session_id in session_ids:
        session_root = _canonical_session_root(
            repository_root,
            workspace_id=workspace_id,
            session_id=session_id,
        )
        document = _read_session_document(
            session_root / "session.json",
            session_id=session_id,
        )
        binding = document.get("execution_binding")
        runtime_engine_id = (
            str(binding.get("runtime_engine_id") or "").strip()
            if isinstance(binding, dict)
            else ""
        )
        if runtime_engine_id == "codex" or str(
            document.get("provider_id") or ""
        ).strip() == "codex":
            roots.add(
                str(document.get("lineage_root_session_id") or session_id).strip()
            )
    return roots


def _provider_conversation_paths(codex_home: Path) -> list[Path]:
    candidates: list[Path] = []
    for sqlite_root in (codex_home, codex_home / ".codex"):
        if sqlite_root.is_symlink():
            raise RuntimeError("runtime_continuation_snapshot_provider_path_unsafe")
        if sqlite_root.is_dir():
            candidates.extend(sqlite_root.glob("state_*.sqlite"))
    for rollout_root in (
        codex_home / "sessions",
        codex_home / "archived_sessions",
    ):
        candidates.extend(_safe_rollout_paths(rollout_root))
    paths: list[Path] = []
    for path in sorted(set(candidates)):
        if path.is_file():
            _require_safe_provider_path(codex_home, path)
            paths.append(path)
    return paths


def _safe_rollout_paths(root: Path) -> list[Path]:
    if root.is_symlink():
        raise RuntimeError("runtime_continuation_snapshot_provider_path_unsafe")
    if not root.is_dir():
        return []
    paths: list[Path] = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RuntimeError("runtime_continuation_snapshot_provider_path_unsafe")
        if path.is_file() and path.suffix == ".jsonl":
            paths.append(path)
    return paths


def _require_safe_provider_path(codex_home: Path, path: Path) -> None:
    resolved_home = codex_home.resolve(strict=True)
    if path.is_symlink():
        raise RuntimeError("runtime_continuation_snapshot_provider_path_unsafe")
    current = path.parent
    while current != codex_home:
        if current.is_symlink() or codex_home not in current.parents:
            raise RuntimeError("runtime_continuation_snapshot_provider_path_unsafe")
        current = current.parent
    try:
        path.resolve(strict=True).relative_to(resolved_home)
    except (OSError, RuntimeError, ValueError) as error:
        raise RuntimeError(
            "runtime_continuation_snapshot_provider_path_unsafe"
        ) from error


def _canonical_session_root(
    repository_root: Path,
    *,
    workspace_id: str,
    session_id: str,
) -> Path:
    session_root = runtime_session_root(
        workspace_id=workspace_id,
        session_id=session_id,
        start_path=repository_root,
    )
    try:
        resolved_sessions_root = session_root.parent.resolve(strict=True)
        resolved_session_root = session_root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise RuntimeError("runtime_continuation_snapshot_session_invalid") from error
    if session_root.is_symlink() or resolved_session_root.parent != resolved_sessions_root:
        raise RuntimeError("runtime_continuation_snapshot_session_unsafe")
    return resolved_session_root


def _backup_sqlite(source: Path, target: Path) -> None:
    source_uri = f"file:{quote(str(source.resolve(strict=True)))}?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True)) as source_connection:
        with closing(sqlite3.connect(target)) as target_connection:
            source_connection.backup(target_connection)
            target_connection.commit()
            result = target_connection.execute("PRAGMA quick_check").fetchone()
            if result != ("ok",):
                raise RuntimeError("runtime_continuation_snapshot_sqlite_invalid")
    target.chmod(0o600)


def _read_session_document(
    path: Path,
    *,
    session_id: str,
) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError("runtime_continuation_snapshot_session_invalid") from error
    if isinstance(payload, dict):
        candidates = [payload]
    elif isinstance(payload, list):
        candidates = [item for item in payload if isinstance(item, dict)]
    else:
        candidates = []
    matches = [
        item
        for item in candidates
        if str(item.get("session_id") or "").strip() == session_id
    ]
    if len(matches) != 1:
        raise RuntimeError("runtime_continuation_snapshot_session_invalid")
    return matches[0]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _make_private_tree(path: Path, *, stop: Path) -> None:
    current = path
    while True:
        current.chmod(0o700)
        if current == stop:
            return
        if stop not in current.parents:
            raise RuntimeError("runtime_continuation_snapshot_path_escape")
        current = current.parent
