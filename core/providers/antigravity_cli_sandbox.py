"""Confined launch data for the Antigravity CLI native candidate."""

from __future__ import annotations

import os
from pathlib import Path
import shutil

from core.providers.antigravity_cli_runtime_home import (
    prepare_antigravity_runtime_home,
)
from core.providers.models import RuntimeBackendLaunchSpec
from core.providers.native_structured_cli_transport import NativeStructuredCliError
from core.runtime.workspace_sandbox import build_bwrap_command


ANTIGRAVITY_DEFAULT_MODEL = "gemini-3.6-flash-high"


def antigravity_stream_launch_spec(
    context,
    *,
    command: str,
    dependency_roots,
    auth_home: str | Path | None = None,
):
    """Build the machine-readable command with a private OAuth profile copy."""
    session = context.session
    secret_env = getattr(context, "secret_env", None)
    if secret_env or getattr(context.binding, "credential_binding_id", None):
        raise NativeStructuredCliError("antigravity_oauth_boundary_invalid")
    workspace = Path(session.workspace_root).resolve(strict=True)
    workdir = Path(session.workdir).resolve(strict=True)
    runtime = Path(session.runtime_root).resolve(strict=False)
    if session.effective_mode != "sandbox" or workdir != workspace:
        raise NativeStructuredCliError("antigravity_workspace_boundary_invalid")
    executable = shutil.which(command)
    if executable is None:
        raise NativeStructuredCliError("native_runtime_not_installed")
    executable_path = Path(executable).resolve(strict=True)
    home = prepare_antigravity_runtime_home(runtime, source_home=auth_home)
    log_path = runtime / "antigravity-cli.log"

    argv = [
        str(executable_path),
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--sandbox",
        "--mode",
        "accept-edits",
        "--disable-slash-commands",
        "--print-timeout",
        "5m",
        "--log-file",
        str(log_path),
    ]
    model_id = str(context.binding.model_id or "").strip()
    if not model_id:
        raise NativeStructuredCliError("antigravity_model_missing")
    argv.extend(["--model", model_id])
    reasoning_effort = str(getattr(context.binding, "reasoning_effort", None) or "").strip()
    if reasoning_effort:
        if reasoning_effort not in {"low", "medium", "high"}:
            raise NativeStructuredCliError("antigravity_reasoning_effort_invalid")
        argv.extend(["--effort", reasoning_effort])

    dependencies = [executable_path.parent, *dependency_roots]
    sandboxed = build_bwrap_command(
        workspace_root=workspace,
        runtime_root=runtime,
        home_root=home,
        dependency_roots=dependencies,
        command=argv,
    )
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_STATE_HOME": str(home / ".local/state"),
        "LANG": "C.UTF-8",
        "NO_COLOR": "1",
        "TMPDIR": str(runtime),
    }
    return RuntimeBackendLaunchSpec(
        provider_id="antigravity-cli",
        command=sandboxed,
        env_overrides=env,
        credential_binding_id=None,
        resolved_secret_refs=[],
        working_directory=str(workdir),
        execution_mode="sandbox",
        readable_roots=[str(workspace), str(runtime), *map(os.fspath, dependencies)],
        writable_roots=[str(workspace), str(runtime)],
    )


__all__ = ["ANTIGRAVITY_DEFAULT_MODEL", "antigravity_stream_launch_spec"]
