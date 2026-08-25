"""Fail-closed local evidence checks for Codex thread resume."""

from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
from urllib.parse import quote

from core.providers.codex_app_server_runtime_errors import CodexAppServerRequestError
from core.providers.codex_app_server_runtime_state import _CodexAppServerRuntime


def resume_error_is_missing_thread(error: CodexAppServerRequestError) -> bool:
    """Return whether a structured rejection proves thread/archive absence."""
    detail = " ".join(
        (
            str(error.message or ""),
            json.dumps(error.data, sort_keys=True, default=str),
        )
    ).casefold()
    strong_marker = any(
        marker in detail
        for marker in (
            "thread not found",
            "unknown thread",
            "missing thread",
            "rollout not found",
            "no rollout",
            "failed to load rollout",
        )
    )
    missing_rollout_path = "no such file or directory" in detail and any(
        marker in detail for marker in ("thread", "rollout", ".jsonl")
    )
    return strong_marker or missing_rollout_path


def local_resume_archive_problem(
    runtime: _CodexAppServerRuntime,
    provider_thread_id: str,
) -> str | None:
    """Return definitive local archive failure evidence before thread/resume."""
    raw_home = str(runtime.runtime_home or "").strip()
    if not raw_home:
        return None
    home = Path(raw_home)
    try:
        resolved_home = home.resolve(strict=True)
    except (OSError, RuntimeError):
        return "missing"
    if home.is_symlink() or not resolved_home.is_dir():
        return "unsafe"
    nested_home = resolved_home / ".codex"
    if nested_home.is_symlink():
        return "unsafe"
    databases = sorted(
        {
            *resolved_home.glob("state_*.sqlite"),
            *nested_home.glob("state_*.sqlite"),
        }
    )
    if not databases:
        return "missing"
    unreadable = False
    found_thread = False
    unsafe = False
    for database in databases:
        if database.is_symlink():
            unsafe = True
            continue
        try:
            resolved_database = database.resolve(strict=True)
        except (OSError, RuntimeError):
            unreadable = True
            continue
        try:
            resolved_database.relative_to(resolved_home)
        except ValueError:
            unsafe = True
            continue
        try:
            uri = f"file:{quote(str(resolved_database))}?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as connection:
                row = connection.execute(
                    "SELECT rollout_path FROM threads WHERE id = ?",
                    (provider_thread_id,),
                ).fetchone()
        except sqlite3.Error:
            unreadable = True
            continue
        if row is None:
            continue
        found_thread = True
        rollout = Path(str(row[0] or "").strip())
        if not rollout.is_absolute():
            unsafe = True
            continue
        try:
            resolved_rollout = rollout.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        try:
            resolved_rollout.relative_to(resolved_home)
        except ValueError:
            unsafe = True
            continue
        if rollout.is_symlink() or not resolved_rollout.is_file():
            unsafe = True
            continue
        return None
    if unsafe:
        return "unsafe"
    if found_thread or not unreadable:
        return "missing"
    return None
