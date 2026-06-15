"""Managed Codex runtime config policy rendering."""

from __future__ import annotations

import json
import os
from pathlib import Path

from core.providers.provider_codex_hooks import CODEX_POST_TOOL_USE_HOOK_NAME


CODEX_MANAGED_SHELL_ENVIRONMENT_NAMES = (
    "PATH",
    "HOME",
    "TMPDIR",
    "TMP",
    "TEMP",
    "CODEX_HOME",
    "MAVERICK_API_BASE",
    "MAVERICK_EFFECTIVE_MODE",
    "MAVERICK_RUNTIME_API_TOKEN",
    "MAVERICK_RUNTIME_BIN",
    "MAVERICK_RUNTIME_CLI_OUTPUT_PROFILE",
    "MAVERICK_RUNTIME_OUTPUT_COMPACTION",
    "MAVERICK_RUNTIME_ROOT",
    "MAVERICK_RUNTIME_SESSION_ID",
    "MAVERICK_WORKSPACE_ID",
    "MAVERICK_WORKSPACE_ROOT",
)


def is_managed_shell_environment_section(section: str) -> bool:
    table = _section_table(section)
    return table == "shell_environment_policy" or table.startswith("shell_environment_policy.")


def is_managed_codex_hook_section(section: str) -> bool:
    table = _section_table(section)
    return table == "hooks" or table.startswith("hooks.")


def managed_shell_environment_policy_lines(
    *,
    workspace_root: Path,
    runtime_root: Path,
    runtime_bin: Path,
    execution_mode: str,
    shell_path: str | None = None,
) -> list[str]:
    path_value = str(shell_path or "").strip()
    if not path_value:
        path_value = os.pathsep.join(
            _dedupe_path_entries(
                [
                    str(runtime_bin),
                    *str(os.environ.get("PATH") or "").split(os.pathsep),
                ]
            )
        )
    api_base = str(os.environ.get("MAVERICK_API_BASE") or "http://127.0.0.1:8014").rstrip("/")
    return [
        "[shell_environment_policy]",
        'inherit = "all"',
        "ignore_default_excludes = true",
        "include_only = [",
        *[f"  {_toml_string(name)}," for name in CODEX_MANAGED_SHELL_ENVIRONMENT_NAMES],
        "]",
        "",
        "[shell_environment_policy.set]",
        f"PATH = {_toml_string(path_value)}",
        f"MAVERICK_RUNTIME_BIN = {_toml_string(str(runtime_bin))}",
        f"MAVERICK_RUNTIME_ROOT = {_toml_string(str(runtime_root))}",
        f"MAVERICK_WORKSPACE_ROOT = {_toml_string(str(workspace_root))}",
        f"MAVERICK_EFFECTIVE_MODE = {_toml_string(execution_mode)}",
        f"MAVERICK_API_BASE = {_toml_string(api_base)}",
    ]


def managed_codex_hook_lines(*, runtime_bin: Path) -> list[str]:
    hook_path = runtime_bin / CODEX_POST_TOOL_USE_HOOK_NAME
    return [
        "[[hooks.PostToolUse]]",
        'matcher = "^Bash$"',
        "",
        "[[hooks.PostToolUse.hooks]]",
        'type = "command"',
        f"command = {_toml_string(str(hook_path))}",
        "timeout = 30",
        'statusMessage = "Compacting shell output"',
    ]


def _section_table(section: str) -> str:
    return section.strip().lstrip("[").rstrip("]").strip()


def _dedupe_path_entries(entries: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        normalized = str(entry or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)
