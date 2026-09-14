"""Unconfined command execution for an explicitly authorized full-access turn."""

from __future__ import annotations

import os
from pathlib import Path
import selectors
import subprocess
import time

from core.runtime.hosted_process_termination import terminate_hosted_process
from core.runtime.runtime_cli_wrapper import write_runtime_maverick_wrapper
from core.runtime.runtime_paths import RuntimePathResolver
from core.runtime.tool_errors import RuntimeToolError


def full_access_process_environment(
    *,
    workspace_id: str,
    session_id: str,
    workspace_root: Path,
    runtime_api_token: str | None = None,
    additional_path_entries: tuple[str, ...] = (),
) -> dict[str, str]:
    """Prepare the host CLI environment and session-owned runtime shims."""
    environment = dict(os.environ)
    session_root = workspace_root / "runtime" / "sessions" / session_id
    session_bin = session_root / "bin"
    write_runtime_maverick_wrapper(session_bin / "maverick")
    inherited_path = environment.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    path_entries = dict.fromkeys(
        (
            str(session_bin),
            *additional_path_entries,
            *inherited_path.split(os.pathsep),
        )
    )
    environment.update(
        {
            "PATH": os.pathsep.join(entry for entry in path_entries if entry),
            "MAVERICK_EFFECTIVE_MODE": "full-access",
            "MAVERICK_RUNTIME_BIN": str(session_bin),
            "MAVERICK_RUNTIME_ROOT": str(session_root),
            "MAVERICK_RUNTIME_SESSION_ID": session_id,
            "MAVERICK_RUNTIME_ENGINE_ID": "maverick-hosted-tool-process",
            "MAVERICK_RUNTIME_CLI_OUTPUT_PROFILE": "provider_compact",
            "MAVERICK_WORKSPACE_ID": workspace_id,
            "MAVERICK_WORKSPACE_ROOT": str(workspace_root),
        }
    )
    if runtime_api_token:
        environment["MAVERICK_RUNTIME_API_TOKEN"] = runtime_api_token
    else:
        environment.pop("MAVERICK_RUNTIME_API_TOKEN", None)
    return environment


def run_full_access_command(
    *,
    workspace_id: str,
    workspace_root: Path,
    argv: list[str],
    cwd: str,
    environment: dict[str, str],
    timeout_seconds: int,
    max_output_bytes: int,
    execution_control=None,
    spawn_observer=None,
) -> dict[str, object]:
    """Run one host command without sandboxing or response rewriting."""
    resolved_cwd = RuntimePathResolver(
        workspace_id=workspace_id,
        workspace_root=workspace_root,
        execution_mode="full-access",
    ).resolve(cwd, allow_root=True).absolute
    if not resolved_cwd.is_dir():
        raise RuntimeToolError("filesystem_path_not_directory")
    process: subprocess.Popen[bytes] | None = None
    try:
        if execution_control is not None:
            execution_control.check()
        process = subprocess.Popen(
            argv,
            cwd=resolved_cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        if spawn_observer is not None:
            spawn_observer("shell")
        if execution_control is not None:
            execution_control.add_cancellation_callback(
                lambda: terminate_hosted_process(process)
            )
        output = _read_output(
            process,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            execution_control=execution_control,
        )
        return {
            "exit_code": int(process.returncode),
            "output": output.decode("utf-8", errors="replace"),
            "output_bytes": len(output),
            "stream_complete": True,
        }
    except RuntimeToolError:
        raise
    except OSError as error:
        if process is not None:
            terminate_hosted_process(process)
        raise RuntimeToolError("shell_execution_failed") from error
    finally:
        if process is not None and process.stdout is not None:
            process.stdout.close()


def _read_output(process, *, timeout_seconds, max_output_bytes, execution_control):
    if process.stdout is None:
        raise RuntimeToolError("shell_execution_failed")
    deadline = time.monotonic() + timeout_seconds
    output = bytearray()
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while True:
            if execution_control is not None:
                try:
                    execution_control.check()
                except RuntimeToolError:
                    terminate_hosted_process(process)
                    raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                terminate_hosted_process(process)
                raise RuntimeToolError("shell_execution_timed_out")
            if not selector.select(timeout=min(remaining, 0.1)):
                continue
            chunk = os.read(process.stdout.fileno(), 65_536)
            if not chunk:
                break
            if len(output) + len(chunk) > max_output_bytes:
                terminate_hosted_process(process)
                raise RuntimeToolError("shell_output_too_large")
            output.extend(chunk)
        process.wait(timeout=max(0.1, deadline - time.monotonic()))
        return bytes(output)
    except subprocess.TimeoutExpired as error:
        terminate_hosted_process(process)
        raise RuntimeToolError("shell_execution_timed_out") from error
    finally:
        selector.close()


__all__ = ["full_access_process_environment", "run_full_access_command"]
