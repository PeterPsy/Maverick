"""In-memory launch context cache for warm runtime turns."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from threading import Lock

from core.runtime.runtime_session import RuntimeSessionRecord
from core.skills.catalog import DEFAULT_SKILL_CATALOG_APP_ID


@dataclass(frozen=True)
class CachedRuntimeLaunchContext:
    fingerprint: str
    launch_spec: object
    metadata: dict[str, object]


_LAUNCH_CONTEXT_CACHE: dict[str, CachedRuntimeLaunchContext] = {}
_LAUNCH_CONTEXT_CACHE_LOCK = Lock()
_CODEX_PROVIDER_ID = "codex"


def clear_cached_runtime_launch_context(session_id: str) -> None:
    """Forget in-memory launch context for a runtime session."""
    with _LAUNCH_CONTEXT_CACHE_LOCK:
        _LAUNCH_CONTEXT_CACHE.pop(session_id, None)


def get_cached_runtime_launch_context(
    *,
    session_id: str,
    fingerprint: str,
) -> CachedRuntimeLaunchContext | None:
    with _LAUNCH_CONTEXT_CACHE_LOCK:
        cached = _LAUNCH_CONTEXT_CACHE.get(session_id)
    if cached is None or cached.fingerprint != fingerprint:
        return None
    return cached


def cache_runtime_launch_context(
    *,
    session_id: str,
    fingerprint: str,
    launch_spec: object,
    metadata: dict[str, object],
) -> None:
    with _LAUNCH_CONTEXT_CACHE_LOCK:
        _LAUNCH_CONTEXT_CACHE[session_id] = CachedRuntimeLaunchContext(
            fingerprint=fingerprint,
            launch_spec=launch_spec,
            metadata=metadata,
        )


def build_runtime_launch_context_fingerprint(
    state,
    *,
    session: RuntimeSessionRecord,
    provider_id: str,
    provider_definition,
    provider_selection,
) -> str | None:
    if provider_id != _CODEX_PROVIDER_ID:
        return None
    catalog_app_id = session.skill_catalog_app_id or DEFAULT_SKILL_CATALOG_APP_ID
    payload = {
        "version": 1,
        "provider_id": provider_id,
        "workspace_id": session.workspace_id,
        "session_id": session.session_id,
        "effective_mode": session.effective_mode,
        "workspace_root": session.workspace_root,
        "workdir": session.workdir,
        "runtime_root": session.runtime_root,
        "skill_ids": list(session.skill_ids),
        "skill_catalog_app_id": catalog_app_id,
        "model_id": getattr(provider_selection, "model_id", None),
        "model_reasoning_effort": getattr(provider_selection, "model_reasoning_effort", None),
        "binding_id": getattr(provider_selection, "binding_id", None),
        "definition": _provider_definition_fingerprint(provider_definition),
        "codex_command": os.environ.get("MAVERICK_CODEX_COMMAND", "").strip() or "codex",
        "skill_catalog": _skill_catalog_metadata_fingerprint(
            workspace_id=session.workspace_id,
            repository_root=Path(state.repository_root),
            app_id=catalog_app_id,
            skill_ids=session.skill_ids,
        ),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _provider_definition_fingerprint(provider_definition) -> dict[str, object]:
    if provider_definition is None:
        return {}
    return {
        "provider_id": getattr(provider_definition, "provider_id", None),
        "status": getattr(provider_definition, "status", None),
        "default_model_family": getattr(provider_definition, "default_model_family", None),
        "model_options": [
            {
                "model_id": getattr(option, "model_id", None),
                "default_reasoning_effort": getattr(option, "default_reasoning_effort", None),
            }
            for option in getattr(provider_definition, "model_options", []) or []
        ],
    }


def _skill_catalog_metadata_fingerprint(
    *,
    workspace_id: str,
    repository_root: Path,
    app_id: str,
    skill_ids: list[str],
) -> dict[str, object]:
    data_root = repository_root / "workspaces" / workspace_id / "data" / app_id
    skills_root = data_root / "skills"
    requested = [str(skill_id or "").strip() for skill_id in skill_ids if str(skill_id or "").strip()]
    metadata: dict[str, object] = {
        "state_json": _file_metadata(data_root / "state.json"),
        "skills_root": str(skills_root),
        "requested": requested,
        "skills": [],
    }
    if not skills_root.is_dir():
        return metadata
    if requested:
        metadata["skills"] = [_requested_skill_metadata(skills_root, skill_id) for skill_id in requested]
    else:
        metadata["skills"] = [
            {"skill_id": skill_root.name, "root": str(skill_root), "metadata_hash": _directory_metadata_hash(skill_root)}
            for skill_root in sorted((path for path in skills_root.iterdir() if path.is_dir()), key=lambda item: item.name)
        ]
    return metadata


def _requested_skill_metadata(skills_root: Path, skill_id: str) -> dict[str, object]:
    if "/" in skill_id or "\\" in skill_id or skill_id in {".", ".."}:
        return {"skill_id": skill_id, "unsafe": True}
    skill_root = skills_root / skill_id
    return {"skill_id": skill_id, "root": str(skill_root), "metadata_hash": _directory_metadata_hash(skill_root)}


def _file_metadata(path: Path) -> dict[str, object]:
    try:
        stat = path.stat()
    except OSError:
        return {"exists": False, "path": str(path)}
    return {"exists": True, "path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _directory_metadata_hash(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        digest.update(b"missing")
        digest.update(str(root).encode("utf-8"))
        return digest.hexdigest()
    if not root.is_dir():
        digest.update(b"not-dir")
        digest.update(str(root).encode("utf-8"))
        return digest.hexdigest()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        try:
            stat = path.stat()
        except OSError:
            digest.update(b"unreadable")
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(b"dir" if path.is_dir() else b"file")
        digest.update(b"\0")
        digest.update(str(stat.st_size).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(stat.st_mtime_ns).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()
