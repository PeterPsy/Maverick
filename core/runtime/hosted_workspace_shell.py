"""Bubblewrap-confined command preparation for hosted workspace tools."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import time

from core.runtime.confined_filesystem import ConfinedWorkspaceFilesystem
from core.runtime.tool_errors import RuntimeToolError


_SYSTEM_DEPENDENCY_ROOTS = ("/usr", "/bin", "/lib", "/lib64")
_ESSENTIAL_FILES = (
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/ssl/cert.pem",
    "/etc/pki/tls/certs/ca-bundle.crt",
)
_SANDBOX_WORKSPACE_ROOT = Path("/workspace")
_SANDBOX_RUNTIME_ROOT = Path("/runtime")


@dataclass
class PreparedHostedWorkspaceCommand:
    """One sandbox command retaining every descriptor required until spawn."""

    command: list[str]
    pass_fds: tuple[int, ...]
    filesystem: ConfinedWorkspaceFilesystem
    cwd_chain: object

    def close(self) -> None:
        """Release retained parent descriptors after the child has spawned."""
        self.cwd_chain.close()  # type: ignore[attr-defined]
        for descriptor in self.pass_fds:
            try:
                os.close(descriptor)
            except OSError:
                pass

    def validate_and_close(self) -> None:
        try:
            self.filesystem.assert_shell_cwd(self.cwd_chain)  # type: ignore[arg-type]
        finally:
            self.close()


def prepare_hosted_workspace_command(
    filesystem: ConfinedWorkspaceFilesystem,
    *,
    workspace_root: Path,
    runtime_root: Path,
    argv: list[str],
    cwd: str,
) -> PreparedHostedWorkspaceCommand:
    """Build a workspace-write-only process command from retained descriptors."""
    if not argv:
        raise RuntimeToolError("tool_arguments_invalid")
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise RuntimeToolError("workspace_shell_sandbox_unavailable")
    cwd_chain = filesystem.open_shell_cwd(cwd)
    root_fd = filesystem.duplicate_root_fd()
    try:
        workspace = Path(os.path.abspath(os.fspath(workspace_root)))
        runtime = Path(os.path.abspath(os.fspath(runtime_root)))
        if workspace != filesystem.workspace_root or runtime != workspace / "runtime":
            raise RuntimeToolError("workspace_shell_root_mismatch")
        runtime_fd = filesystem.open_platform_runtime_fd(runtime)
        os.close(runtime_fd)
        relative_cwd = filesystem._relative(
            filesystem._components(cwd, allow_root=True)
        )
        command = _build_bwrap_command(
            bwrap=bwrap,
            root_fd=root_fd,
            relative_cwd=relative_cwd,
            argv=argv,
        )
        return PreparedHostedWorkspaceCommand(
            command=command,
            pass_fds=(root_fd,),
            filesystem=filesystem,
            cwd_chain=cwd_chain,
        )
    except Exception:
        cwd_chain.close()
        os.close(root_fd)
        raise


def run_hosted_workspace_command(
    filesystem: ConfinedWorkspaceFilesystem,
    *,
    workspace_root: Path,
    runtime_root: Path,
    argv: list[str],
    cwd: str,
    environment: dict[str, str],
    timeout_seconds: int,
    max_output_bytes: int,
) -> dict[str, object]:
    """Run one bounded command and kill its complete process group on timeout."""
    prepared = prepare_hosted_workspace_command(
        filesystem,
        workspace_root=workspace_root,
        runtime_root=runtime_root,
        argv=argv,
        cwd=cwd,
    )
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            prepared.command,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            pass_fds=prepared.pass_fds,
            start_new_session=True,
        )
        try:
            output = _read_bounded_output(
                process,
                timeout_seconds=timeout_seconds,
                max_output_bytes=max_output_bytes,
            )
        finally:
            if process.stdout is not None:
                process.stdout.close()
        prepared.filesystem.assert_shell_cwd(prepared.cwd_chain)  # type: ignore[arg-type]
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
            _terminate_group(process)
        raise RuntimeToolError("shell_execution_failed") from error
    except Exception as error:
        if process is not None:
            _terminate_group(process)
        raise RuntimeToolError("shell_execution_failed") from error
    finally:
        prepared.close()


def _build_bwrap_command(
    *,
    bwrap: str,
    root_fd: int,
    relative_cwd: str,
    argv: list[str],
) -> list[str]:
    dependency_roots = [
        Path(value) for value in _SYSTEM_DEPENDENCY_ROOTS if Path(value).exists()
    ]
    command = [
        bwrap,
        "--die-with-parent",
        "--new-session",
        "--unshare-pid",
        "--unshare-net",
        "--unshare-ipc",
        "--unshare-uts",
        "--hostname",
        "maverick-workspace",
        "--tmpfs",
        "/",
    ]
    for directory in _parent_directories(
        [
            _SANDBOX_WORKSPACE_ROOT,
            _SANDBOX_RUNTIME_ROOT,
            *dependency_roots,
        ]
    ):
        command.extend(("--dir", str(directory)))
    command.extend(("--proc", "/proc", "--dev", "/dev"))
    for dependency in dependency_roots:
        command.extend(("--ro-bind", str(dependency), str(dependency)))
    for masked in (Path("/usr/share"), Path("/usr/local/share")):
        if masked.exists():
            command.extend(("--tmpfs", str(masked)))
    command.extend(
        (
            "--bind",
            f"/proc/self/fd/{root_fd}",
            str(_SANDBOX_WORKSPACE_ROOT),
            "--tmpfs",
            str(_SANDBOX_WORKSPACE_ROOT / "runtime"),
            "--tmpfs",
            str(_SANDBOX_RUNTIME_ROOT),
            "--dir",
            str(_SANDBOX_RUNTIME_ROOT / "home"),
        )
    )
    for essential in _ESSENTIAL_FILES:
        if Path(essential).is_file():
            command.extend(("--ro-bind-try", essential, essential))
    sandbox_cwd = (
        _SANDBOX_WORKSPACE_ROOT
        if relative_cwd == "."
        else _SANDBOX_WORKSPACE_ROOT / relative_cwd
    )
    command.extend(
        (
            "--setenv",
            "HOME",
            str(_SANDBOX_RUNTIME_ROOT / "home"),
            "--setenv",
            "TMPDIR",
            str(_SANDBOX_RUNTIME_ROOT),
            "--unsetenv",
            "PYTHONPATH",
            "--chdir",
            str(sandbox_cwd),
            "--",
            *argv,
        )
    )
    return command


def _read_bounded_output(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: int,
    max_output_bytes: int,
) -> bytes:
    """Drain one pipe incrementally without ever buffering beyond the ceiling."""
    if process.stdout is None:
        raise RuntimeToolError("shell_execution_failed")
    deadline = time.monotonic() + timeout_seconds
    output = bytearray()
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_group(process)
                raise RuntimeToolError("shell_execution_timed_out")
            events = selector.select(timeout=min(remaining, 0.1))
            if not events:
                continue
            chunk = os.read(process.stdout.fileno(), 65_536)
            if not chunk:
                break
            if len(output) + len(chunk) > max_output_bytes:
                _terminate_group(process)
                raise RuntimeToolError("shell_output_too_large")
            output.extend(chunk)
        process.wait(timeout=max(0.1, deadline - time.monotonic()))
        return bytes(output)
    except subprocess.TimeoutExpired as error:
        _terminate_group(process)
        raise RuntimeToolError("shell_execution_timed_out") from error
    finally:
        selector.close()


def _parent_directories(paths: list[Path]) -> list[Path]:
    values: set[str] = set()
    for path in paths:
        current = path
        while str(current) not in {"", "/"}:
            values.add(str(current))
            current = current.parent
    return [Path(value) for value in sorted(values, key=lambda item: (item.count("/"), item))]


def _terminate_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=1.0)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass
