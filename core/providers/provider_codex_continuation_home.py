"""Canonical Codex conversation-home ownership across continuation forks."""

from __future__ import annotations

from pathlib import Path

from core.providers.errors import ProviderLaunchError
from core.runtime.paths import normalize_runtime_session_id
from core.runtime.runtime_session import RuntimeSessionRecord


def resolve_codex_runtime_home(session: RuntimeSessionRecord) -> Path:
    """Return the session home or its fenced continuation lineage's root home."""
    runtime_root = Path(session.runtime_root)
    own_runtime_home = runtime_root / "codex-home"
    predecessor_session_id = str(
        getattr(session, "predecessor_session_id", None) or ""
    ).strip()
    lineage_root_session_id = str(
        getattr(session, "lineage_root_session_id", None) or ""
    ).strip()
    continuation_handoff_id = str(
        getattr(session, "continuation_handoff_id", None) or ""
    ).strip()
    lineage_markers = (
        predecessor_session_id,
        lineage_root_session_id,
        continuation_handoff_id,
    )
    if not any(lineage_markers):
        return own_runtime_home
    if not all(lineage_markers):
        raise _continuation_home_error("codex_continuation_runtime_home_unsafe")
    try:
        normalized_session_id = normalize_runtime_session_id(session.session_id)
        normalized_predecessor_id = normalize_runtime_session_id(
            predecessor_session_id
        )
        normalized_lineage_root_id = normalize_runtime_session_id(
            lineage_root_session_id
        )
    except ValueError as error:
        raise _continuation_home_error(
            "codex_continuation_runtime_home_unsafe"
        ) from error
    if (
        runtime_root.name != normalized_session_id
        or normalized_predecessor_id == normalized_session_id
        or normalized_lineage_root_id == normalized_session_id
    ):
        raise _continuation_home_error("codex_continuation_runtime_home_unsafe")
    sessions_root = runtime_root.parent
    lineage_root = sessions_root / normalized_lineage_root_id
    try:
        resolved_sessions_root = sessions_root.resolve(strict=True)
        resolved_runtime_root = runtime_root.resolve(strict=True)
        resolved_lineage_root = lineage_root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise _continuation_home_error(
            "codex_continuation_runtime_home_missing"
        ) from error
    if (
        runtime_root.is_symlink()
        or lineage_root.is_symlink()
        or resolved_runtime_root.parent != resolved_sessions_root
        or resolved_lineage_root.parent != resolved_sessions_root
    ):
        raise _continuation_home_error("codex_continuation_runtime_home_unsafe")
    runtime_home = resolved_lineage_root / "codex-home"
    if runtime_home.is_symlink() or not runtime_home.is_dir():
        raise _continuation_home_error("codex_continuation_runtime_home_missing")
    return runtime_home


def _continuation_home_error(message: str) -> ProviderLaunchError:
    return ProviderLaunchError(message, reason_code="provider_thread_missing")
