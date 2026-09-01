"""Bubblewrap-confined command preparation for hosted workspace tools."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import selectors
import shutil
import signal
import stat
import subprocess
import time

from core.runtime.confined_filesystem import ConfinedWorkspaceFilesystem
from core.runtime.hosted_workspace_effects import (
    HostedWorkspaceEffectOverlay,
    HostedWorkspaceMutationScope,
)
from core.runtime.hosted_result_authority_guard import (
    HostedResultAuthorityGuard,
)
from core.runtime.tool_errors import RuntimeToolError
from core.runtime.tool_catalog import RuntimeToolSurfaceResult


_SYSTEM_DEPENDENCY_ROOTS = ("/usr", "/bin", "/lib", "/lib64")
_ESSENTIAL_FILES = (
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/ssl/cert.pem",
    "/etc/pki/tls/certs/ca-bundle.crt",
)
_SANDBOX_WORKSPACE_ROOT = Path("/workspace")
_SANDBOX_RUNTIME_ROOT = Path("/runtime")
_SANDBOX_LOWER_ROOT = _SANDBOX_RUNTIME_ROOT / "workspace-lower"


@dataclass
class PreparedHostedWorkspaceCommand:
    """One sandbox command retaining every descriptor required until spawn."""

    command: list[str]
    pass_fds: tuple[int, ...]
    filesystem: ConfinedWorkspaceFilesystem
    cwd_chain: object
    effect_overlay: HostedWorkspaceEffectOverlay | None = None

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
    mutation_scopes: tuple[HostedWorkspaceMutationScope, ...] = (),
) -> PreparedHostedWorkspaceCommand:
    """Build a COW-governed process command from retained descriptors."""
    if not argv:
        raise RuntimeToolError("tool_arguments_invalid")
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise RuntimeToolError("workspace_shell_sandbox_unavailable")
    cwd_chain = filesystem.open_shell_cwd(cwd)
    root_fd = filesystem.duplicate_root_fd()
    effect_overlay: HostedWorkspaceEffectOverlay | None = None
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
        if mutation_scopes:
            effect_overlay = HostedWorkspaceEffectOverlay.create(
                filesystem,
                workspace_root=workspace,
                runtime_root=runtime,
                scopes=mutation_scopes,
            )
        command = _build_bwrap_command(
            bwrap=bwrap,
            root_fd=root_fd,
            relative_cwd=relative_cwd,
            argv=argv,
            effect_overlay=effect_overlay,
            git_metadata_kind=_git_metadata_kind(root_fd),
        )
        return PreparedHostedWorkspaceCommand(
            command=command,
            pass_fds=(root_fd,),
            filesystem=filesystem,
            cwd_chain=cwd_chain,
            effect_overlay=effect_overlay,
        )
    except Exception:
        if effect_overlay is not None:
            effect_overlay.discard()
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
    mutation_scopes: tuple[HostedWorkspaceMutationScope, ...] = (),
    execution_control=None,
    result_classification_resolver=None,
    result_context=None,
    result_arguments: dict[str, object] | None = None,
) -> dict[str, object] | RuntimeToolSurfaceResult:
    """Run one bounded command and kill its complete process group on timeout."""
    if execution_control is not None:
        execution_control.check()
    prepared = prepare_hosted_workspace_command(
        filesystem,
        workspace_root=workspace_root,
        runtime_root=runtime_root,
        argv=argv,
        cwd=cwd,
        mutation_scopes=mutation_scopes,
    )
    process: subprocess.Popen[bytes] | None = None
    try:
        if prepared.effect_overlay is not None:
            prepared.effect_overlay.verify_before_spawn()
        process = subprocess.Popen(
            prepared.command,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            pass_fds=prepared.pass_fds,
            start_new_session=True,
        )
        if execution_control is not None:
            execution_control.add_cancellation_callback(
                lambda: _cancel_workspace_command(process, prepared)
            )
            execution_control.check()
        try:
            output = _read_bounded_output(
                process,
                timeout_seconds=timeout_seconds,
                max_output_bytes=max_output_bytes,
                execution_control=execution_control,
            )
        finally:
            if process.stdout is not None:
                process.stdout.close()
        prepared.filesystem.assert_shell_cwd(prepared.cwd_chain)  # type: ignore[arg-type]
        if execution_control is not None:
            execution_control.check()
        precommitted_classification = None
        result_authority_guard = None
        if prepared.effect_overlay is None:
            effect_evidence = {
                "workspace_effects_committed": True,
                "workspace_effect_count": 0,
                "workspace_effect_paths": (),
                "mutation_scope_count": 0,
            }
        elif process.returncode == 0:
            expected_evidence = prepared.effect_overlay.preview_commit()
            intended = {
                "exit_code": int(process.returncode),
                "output": output.decode("utf-8", errors="replace"),
                "output_bytes": len(output),
                "stream_complete": True,
                **expected_evidence,
            }
            if result_classification_resolver is not None:
                try:
                    resolved = result_classification_resolver(
                        "core-capability:shell.run",
                        result_arguments or {},
                        intended,
                        result_context,
                    )
                except Exception as error:
                    prepared.effect_overlay.discard()
                    raise RuntimeToolError(
                        "tool_result_egress_not_guaranteed"
                    ) from error
                if (
                    not isinstance(resolved, RuntimeToolSurfaceResult)
                    or resolved.payload != intended
                    or resolved.classification.data_class != "public"
                ):
                    prepared.effect_overlay.discard()
                    raise RuntimeToolError(
                        "tool_result_egress_not_guaranteed"
                    )
                precommitted_classification = resolved.classification
                result_authority_guard = HostedResultAuthorityGuard(
                    resolver=result_classification_resolver,
                    handle="core-capability:shell.run",
                    arguments=result_arguments or {},
                    payload=intended,
                    context=result_context,
                    expected_classification=resolved.classification,
                )
            effect_evidence = (
                execution_control.run_if_active(
                    lambda: prepared.effect_overlay.commit(
                        expected_evidence=expected_evidence,
                        result_authority_guard=result_authority_guard,
                    )
                )
                if execution_control is not None
                else prepared.effect_overlay.commit(
                    expected_evidence=expected_evidence,
                    result_authority_guard=result_authority_guard,
                )
            )
        else:
            effect_evidence = prepared.effect_overlay.discard()
        payload = {
            "exit_code": int(process.returncode),
            "output": output.decode("utf-8", errors="replace"),
            "output_bytes": len(output),
            "stream_complete": True,
            **effect_evidence,
        }
        return (
            RuntimeToolSurfaceResult(payload, precommitted_classification)
            if precommitted_classification is not None
            else payload
        )
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
        if prepared.effect_overlay is not None:
            prepared.effect_overlay.discard()
        prepared.close()


def _build_bwrap_command(
    *,
    bwrap: str,
    root_fd: int,
    relative_cwd: str,
    argv: list[str],
    effect_overlay: HostedWorkspaceEffectOverlay | None,
    git_metadata_kind: str | None,
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
    if effect_overlay is None:
        command.extend(
            (
                "--ro-bind-fd",
                str(root_fd),
                str(_SANDBOX_WORKSPACE_ROOT),
            )
        )
    else:
        command.extend(
            (
                "--overlay-src",
                f"/proc/self/fd/{root_fd}",
                "--overlay",
                str(effect_overlay.upper),
                str(effect_overlay.work),
                str(_SANDBOX_WORKSPACE_ROOT),
                # Consume and close the inherited live-root descriptor after
                # overlay setup.  The temporary mount is masked below before
                # the command starts, preventing openat(2) write bypasses.
                "--dir",
                str(_SANDBOX_LOWER_ROOT),
                "--ro-bind-fd",
                str(root_fd),
                str(_SANDBOX_LOWER_ROOT),
            )
        )
    if git_metadata_kind == "directory":
        command.extend(("--tmpfs", str(_SANDBOX_WORKSPACE_ROOT / ".git")))
    elif git_metadata_kind == "file":
        command.extend(
            ("--ro-bind", "/dev/null", str(_SANDBOX_WORKSPACE_ROOT / ".git"))
        )
    command.extend(
        (
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


def _git_metadata_kind(root_fd: int) -> str | None:
    try:
        metadata = os.stat(".git", dir_fd=root_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if stat.S_ISDIR(metadata.st_mode):
        return "directory"
    if stat.S_ISREG(metadata.st_mode):
        return "file"
    raise RuntimeToolError("workspace_shell_git_metadata_unsafe")


def _read_bounded_output(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: int,
    max_output_bytes: int,
    execution_control=None,
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
            if execution_control is not None:
                try:
                    execution_control.check()
                except RuntimeToolError:
                    _terminate_group(process)
                    raise
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


def _cancel_workspace_command(
    process: subprocess.Popen[bytes],
    prepared: PreparedHostedWorkspaceCommand,
) -> None:
    _terminate_group(process)
    if prepared.effect_overlay is not None:
        prepared.effect_overlay.discard()
