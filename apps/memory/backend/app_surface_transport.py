"""Bounded app-to-app subprocess transport helpers for Memory."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any

from errors import MemoryValidationError


DEFAULT_APP_SURFACE_TIMEOUT_SECONDS = 30.0
MAX_APP_SURFACE_TIMEOUT_SECONDS = 300.0
MAX_APP_SURFACE_RETRIES = 3


def run_maverick_app_mcp(
    workspace_root: Path,
    *,
    app_id: str,
    operation: str,
    tool_name: str = "",
    arguments: dict[str, Any] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = ["maverick", "app", app_id, "mcp", operation, "--json"]
    if operation == "call":
        if not tool_name:
            raise MemoryValidationError("MCP call requires tool_name.")
        command = [
            "maverick",
            "app",
            app_id,
            "mcp",
            "call",
            tool_name,
            "--json",
            *mcp_cli_argument_flags(arguments or {}),
        ]
    elif operation != "list":
        raise MemoryValidationError("unsupported MCP operation.")
    return run_json_subprocess(command, cwd=workspace_root, label=f"{app_id} MCP {operation}")


def run_json_subprocess(command: list[str], *, cwd: Path, label: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    timeout = app_surface_timeout_seconds()
    attempts = app_surface_retries() + 1
    last_completed: subprocess.CompletedProcess[str] | None = None
    for attempt in range(attempts):
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                input=input_text,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            if attempt + 1 < attempts:
                continue
            raise MemoryValidationError(f"{label} timed out after {timeout:g} seconds.") from error
        last_completed = completed
        if completed.returncode == 0 or attempt + 1 >= attempts:
            return completed
    return last_completed or subprocess.CompletedProcess(command, 1, "", "")


def app_surface_timeout_seconds() -> float:
    raw = os.environ.get("MAVERICK_MEMORY_APP_SURFACE_TIMEOUT_SECONDS", "")
    if not raw.strip():
        return DEFAULT_APP_SURFACE_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_APP_SURFACE_TIMEOUT_SECONDS
    if value <= 0:
        return DEFAULT_APP_SURFACE_TIMEOUT_SECONDS
    return min(value, MAX_APP_SURFACE_TIMEOUT_SECONDS)


def app_surface_retries() -> int:
    raw = os.environ.get("MAVERICK_MEMORY_APP_SURFACE_RETRIES", "")
    if not raw.strip():
        return 0
    try:
        value = int(raw)
    except ValueError:
        return 0
    return max(0, min(value, MAX_APP_SURFACE_RETRIES))


def mcp_cli_argument_flags(arguments: dict[str, Any]) -> list[str]:
    cli_args: list[str] = []
    for key, value in arguments.items():
        if value is None or value == "":
            continue
        cli_args.extend([f"--{key.replace('_', '-')}", str(value)])
    return cli_args


def json_response(completed: subprocess.CompletedProcess[str], *, invalid_json_message: str) -> dict[str, Any]:
    try:
        response = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as error:
        raise MemoryValidationError(invalid_json_message) from error
    return response if isinstance(response, dict) else {}
