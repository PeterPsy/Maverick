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
        "version": 2,
        "provider_id": provider_id,
        "workspace_id": session.workspace_id,
        "session_id": session.session_id,
        "effective_mode": session.effective_mode,
        "workspace_root": session.workspace_root,
        "workdir": session.workdir,
        "runtime_root": session.runtime_root,
        "skill_ids": list(session.skill_ids),
        "skill_catalog_app_id": catalog_app_id,
        "skill_activation_mode": session.skill_activation_mode,
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
        "state": _skill_catalog_state_fingerprint(data_root / "state.json", requested_skill_ids=requested),
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
            _skill_root_metadata(skill_root.name, skill_root)
            for skill_root in sorted((path for path in skills_root.iterdir() if path.is_dir()), key=lambda item: item.name)
        ]
    return metadata


def _requested_skill_metadata(skills_root: Path, skill_id: str) -> dict[str, object]:
    if "/" in skill_id or "\\" in skill_id or skill_id in {".", ".."}:
        return {"skill_id": skill_id, "unsafe": True}
    skill_root = skills_root / skill_id
    return _skill_root_metadata(skill_id, skill_root)


def _skill_root_metadata(skill_id: str, skill_root: Path) -> dict[str, object]:
    return {
        "skill_id": skill_id,
        "root": str(skill_root),
        "root_metadata": _file_metadata(skill_root),
        "skill_file": _file_metadata(skill_root / "SKILL.md"),
    }


def _skill_catalog_state_fingerprint(path: Path, *, requested_skill_ids: list[str]) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"exists": False, "skills_metadata": False, "path": str(path)}
    except (OSError, json.JSONDecodeError):
        return {"exists": True, "skills_metadata": False, "readable": False, "path": str(path)}
    if not isinstance(payload, dict):
        return {"exists": True, "skills_metadata": False, "readable": True, "path": str(path)}
    raw_skills = payload.get("skills")
    if not isinstance(raw_skills, list):
        return {"exists": True, "skills_metadata": False, "readable": True, "path": str(path)}
    requested = set(requested_skill_ids)
    entries: list[dict[str, object]] = []
    for raw_skill in raw_skills:
        if not isinstance(raw_skill, dict):
            continue
        skill_id = str(raw_skill.get("id") or "").strip()
        if not skill_id or (requested and skill_id not in requested):
            continue
        entries.append(
            {
                "id": skill_id,
                "local_id": str(raw_skill.get("local_id") or "").strip(),
                "name": str(raw_skill.get("name") or "").strip(),
                "description": str(raw_skill.get("description") or "").strip(),
                "enabled": bool(raw_skill.get("enabled", True)),
                "updated_at": str(raw_skill.get("updated_at") or "").strip(),
            }
        )
    entries.sort(key=lambda item: str(item["id"]))
    digest = hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {
        "exists": True,
        "skills_metadata": True,
        "path": str(path),
        "entry_count": len(entries),
        "metadata_hash": digest,
    }


def _file_metadata(path: Path) -> dict[str, object]:
    try:
        stat = path.stat()
    except OSError:
        return {"exists": False, "path": str(path)}
    return {"exists": True, "path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
