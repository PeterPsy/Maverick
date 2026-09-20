"""Confined launch data for the Antigravity CLI native candidate."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import stat

from core.providers.antigravity_cli_runtime_home import (
    ensure_antigravity_runtime_skills_root,
    prepare_antigravity_runtime_home,
)
from core.runtime.runtime_cli_wrapper import write_runtime_maverick_wrapper
from core.providers.models import RuntimeBackendLaunchSpec
from core.providers.native_structured_cli_transport import NativeStructuredCliError
from core.runtime.workspace_sandbox import build_bwrap_command
from core.runtime.workspace_api_token import issue_workspace_api_token


ANTIGRAVITY_DEFAULT_MODEL = "gemini-3.8-flash-high"
ANTIGRAVITY_OUTER_SANDBOX_COMMAND_ENV = "MAVERICK_ANTIGRAVITY_BWRAP_COMMAND"
ANTIGRAVITY_OUTER_SANDBOX_SHA256 = (
    "41c26bc2e4130e32bcf7cbb304f2686343e1aa657b98226e3daafddf0b21322f"
)
ANTIGRAVITY_OUTER_SANDBOX_OWNER_UID = 0


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
    execution_mode = str(session.effective_mode or "").strip()
    if execution_mode not in {"sandbox", "full-access"} or workdir != workspace:
        raise NativeStructuredCliError("antigravity_workspace_boundary_invalid")
    executable = shutil.which(command)
    if executable is None:
        raise NativeStructuredCliError("native_runtime_not_installed")
    executable_path = Path(executable).resolve(strict=True)
    home = prepare_antigravity_runtime_home(runtime, source_home=auth_home)
    skills_root = ensure_antigravity_runtime_skills_root(runtime)
    workspace_id = str(getattr(session, "workspace_id", "") or "").strip()
    if not workspace_id:
        raise NativeStructuredCliError("antigravity_workspace_identity_missing")
    runtime_bin = runtime / "bin"
    runtime_bin.mkdir(parents=True, exist_ok=True, mode=0o700)
    runtime_bin.chmod(0o700)
    write_runtime_maverick_wrapper(runtime_bin / "maverick")
    log_path = runtime / "antigravity-cli.log"

    argv = [
        str(executable_path),
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--add-dir",
        str(workspace),
    ]
    if execution_mode == "sandbox":
        argv.append("--sandbox")
    else:
        argv.append("--dangerously-skip-permissions")
    argv.extend(
        [
            "--mode",
            "accept-edits",
            "--disable-slash-commands",
            "--print-timeout",
            "5m",
            "--log-file",
            str(log_path),
        ]
    )
    model_id, reasoning_effort = resolve_antigravity_model_selection(
        context.binding
    )
    argv.extend(["--model", model_id])
    if reasoning_effort:
        argv.extend(["--effort", reasoning_effort])

    dependencies = [executable_path.parent, *dependency_roots]
    command_argv = argv
    if execution_mode == "sandbox":
        outer_sandbox = resolve_antigravity_outer_sandbox()
        command_argv = build_bwrap_command(
            workspace_root=workspace,
            runtime_root=runtime,
            home_root=home,
            dependency_roots=dependencies,
            command=argv,
        )
        if outer_sandbox is not None:
            command_argv[0] = str(outer_sandbox)
        command_argv = _readonly_skills_command(
            command_argv,
            skills_root=skills_root,
        )
    env = {
        "PATH": f"{runtime_bin}:/usr/local/bin:/usr/bin:/bin",
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_STATE_HOME": str(home / ".local/state"),
        "LANG": "C.UTF-8",
        "NO_COLOR": "1",
        "TMPDIR": str(runtime),
        "MAVERICK_WORKSPACE_ROOT": str(workspace),
        "MAVERICK_WORKSPACE_ID": workspace_id,
        "MAVERICK_RUNTIME_ROOT": str(runtime),
        "MAVERICK_RUNTIME_BIN": str(runtime_bin),
        "MAVERICK_RUNTIME_SESSION_ID": str(session.session_id),
        "MAVERICK_RUNTIME_ENGINE_ID": "antigravity-cli",
        "MAVERICK_EFFECTIVE_MODE": execution_mode,
        "MAVERICK_RUNTIME_CLI_OUTPUT_PROFILE": "provider_compact",
        "MAVERICK_RUNTIME_API_TOKEN": issue_workspace_api_token(
            workspace_id=workspace_id,
            runtime_session_id=str(session.session_id),
            effective_mode=execution_mode,
        ),
        "MAVERICK_API_BASE": str(
            os.environ.get("MAVERICK_API_BASE") or "http://127.0.0.1:8014"
        ).rstrip("/"),
    }
    return RuntimeBackendLaunchSpec(
        provider_id="antigravity-cli",
        command=command_argv,
        env_overrides=env,
        credential_binding_id=None,
        resolved_secret_refs=[],
        working_directory=str(workdir),
        execution_mode=execution_mode,
        readable_roots=(
            ["/"]
            if execution_mode == "full-access"
            else [str(workspace), str(runtime), *map(os.fspath, dependencies)]
        ),
        writable_roots=(
            ["/"]
            if execution_mode == "full-access"
            else [str(workspace), str(runtime)]
        ),
    )


def resolve_antigravity_outer_sandbox() -> Path | None:
    """Validate the optional reviewed launcher for nested Linux sandboxing."""
    configured = str(
        os.environ.get(ANTIGRAVITY_OUTER_SANDBOX_COMMAND_ENV) or ""
    ).strip()
    if not configured:
        return None
    candidate = Path(configured)
    try:
        details = candidate.stat(follow_symlinks=False)
        resolved = candidate.resolve(strict=True)
        with candidate.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError as error:
        raise NativeStructuredCliError(
            "antigravity_outer_sandbox_invalid"
        ) from error
    if (
        not candidate.is_absolute()
        or resolved != candidate
        or not stat.S_ISREG(details.st_mode)
        or details.st_nlink != 1
        or details.st_uid != ANTIGRAVITY_OUTER_SANDBOX_OWNER_UID
        or details.st_mode & 0o022
        or not details.st_mode & 0o111
        or digest != ANTIGRAVITY_OUTER_SANDBOX_SHA256
    ):
        raise NativeStructuredCliError("antigravity_outer_sandbox_invalid")
    return candidate


def resolve_antigravity_model_selection(binding) -> tuple[str, str | None]:
    """Resolve the catalog alias selected by the canonical effort control."""
    model_id = str(getattr(binding, "model_id", None) or "").strip()
    if not model_id:
        raise NativeStructuredCliError("antigravity_model_missing")
    reasoning_effort = str(
        getattr(binding, "reasoning_effort", None) or ""
    ).strip()
    if not reasoning_effort:
        return model_id, None
    if reasoning_effort not in {"low", "medium", "high"}:
        raise NativeStructuredCliError("antigravity_reasoning_effort_invalid")
    for suffix in ("-low", "-medium", "-high"):
        if model_id.endswith(suffix):
            return f"{model_id[:-len(suffix)]}-{reasoning_effort}", reasoning_effort
    return model_id, reasoning_effort


def _readonly_skills_command(
    command: list[str],
    *,
    skills_root: Path,
) -> list[str]:
    """Shadow the writable runtime mount with an exact read-only skill tree."""
    result = list(command)
    try:
        boundary = result.index("--")
    except ValueError as error:
        raise NativeStructuredCliError(
            "antigravity_workspace_boundary_invalid"
        ) from error
    value = str(skills_root)
    result[boundary:boundary] = ["--ro-bind", value, value]
    return result


__all__ = [
    "ANTIGRAVITY_DEFAULT_MODEL",
    "ANTIGRAVITY_OUTER_SANDBOX_COMMAND_ENV",
    "ANTIGRAVITY_OUTER_SANDBOX_SHA256",
    "antigravity_stream_launch_spec",
    "resolve_antigravity_outer_sandbox",
    "resolve_antigravity_model_selection",
]
