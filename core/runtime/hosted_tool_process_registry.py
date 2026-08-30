"""Session-owned long-running process handles for hosted workspace agents."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import subprocess
from threading import RLock
import time
from uuid import uuid4

from core.runtime.confined_filesystem import ConfinedWorkspaceFilesystem
from core.runtime.hosted_workspace_shell import prepare_hosted_workspace_command
from core.runtime.hosted_workspace_effects import (
    HostedWorkspaceEffectOverlay,
    HostedWorkspaceMutationScope,
)
from core.runtime.hosted_process_output import HostedProcessOutputCapture
from core.runtime.lifecycle_service_turns import (
    create_runtime_process,
    transition_runtime_process,
)
from core.runtime.process_control import (
    register_runtime_process,
    runtime_processes_alive_for_session,
    terminate_orphaned_runtime_processes_for_session,
    terminate_runtime_process,
    unregister_runtime_process,
)
from core.runtime.tool_errors import RuntimeToolError


MAX_PROCESS_STATUS_BYTES = 131_072
MAX_PROCESS_INPUT_BYTES = 65_536
_SESSION_TERMINATION_SWEEP_ATTEMPTS = 4
_SESSION_TERMINATION_SWEEP_TIMEOUT_SECONDS = 0.25
_SESSION_TERMINATION_SWEEP_PAUSE_SECONDS = 0.05


@dataclass
class _LiveHostedToolProcess:
    process: subprocess.Popen[bytes]
    output_fd: int
    output_capture: HostedProcessOutputCapture
    session_id: str
    workspace_id: str
    effect_overlay: HostedWorkspaceEffectOverlay | None
    workspace_effects: dict[str, object] | None = None
    lock: RLock = field(default_factory=RLock, repr=False)


class HostedToolProcessRegistry:
    """Own process handles until terminal status or session-level cleanup."""

    def __init__(self, *, store) -> None:
        self.store = store
        self._live: dict[str, _LiveHostedToolProcess] = {}
        self._lock = RLock()

    def start(
        self,
        *,
        filesystem: ConfinedWorkspaceFilesystem,
        workspace_id: str,
        session_id: str,
        workspace_root: Path,
        runtime_root: Path,
        argv: list[str],
        cwd: str,
        environment: dict[str, str],
        timeout_seconds: int,
        mutation_scopes: tuple[HostedWorkspaceMutationScope, ...] = (),
    ) -> dict[str, object]:
        process_id = f"agent-process-{uuid4().hex}"
        prepared = prepare_hosted_workspace_command(
            filesystem,
            workspace_root=workspace_root,
            runtime_root=runtime_root,
            argv=argv,
            cwd=cwd,
            mutation_scopes=mutation_scopes,
        )
        runtime_fd: int | None = None
        output_directory_fd: int | None = None
        output_fd: int | None = None
        output_name = f"{process_id}.output"
        record = None
        output_handle = None
        output_capture = None
        process: subprocess.Popen[bytes] | None = None
        try:
            runtime_fd = filesystem.open_platform_runtime_fd(runtime_root)
            try:
                os.mkdir("agent-processes", 0o700, dir_fd=runtime_fd)
            except FileExistsError:
                pass
            output_directory_fd = os.open(
                "agent-processes",
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=runtime_fd,
            )
            os.fchmod(output_directory_fd, 0o700)
            record = create_runtime_process(
                self.store,
                process_id=process_id,
                session_id=session_id,
                command=_redacted_command(argv),
                cwd=("." if cwd == "." else cwd),
            )
            output_fd = os.open(
                output_name,
                os.O_RDWR
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=output_directory_fd,
            )
            output_handle = os.fdopen(os.dup(output_fd), "wb", buffering=0)
            if prepared.effect_overlay is not None:
                prepared.effect_overlay.verify_before_spawn()
            process = subprocess.Popen(
                prepared.command,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                pass_fds=prepared.pass_fds,
                start_new_session=True,
            )
            prepared.filesystem.assert_shell_cwd(prepared.cwd_chain)  # type: ignore[arg-type]
            output_capture = HostedProcessOutputCapture(
                process=process,
                output_handle=output_handle,
                timeout_seconds=timeout_seconds,
            )
            output_capture.start()
            register_runtime_process(session_id, process)
            transition_runtime_process(
                self.store,
                process_id=record.process_id,
                target_status="running",
                stdin_open=True,
                stdout_open=True,
            )
            with self._lock:
                self._live[process_id] = _LiveHostedToolProcess(
                    process=process,
                    output_fd=output_fd,
                    output_capture=output_capture,
                    session_id=session_id,
                    workspace_id=workspace_id,
                    effect_overlay=prepared.effect_overlay,
                )
            return {
                "process_id": process_id,
                "status": "running",
                "output_offset": 0,
                "workspace_effects_pending": prepared.effect_overlay is not None,
                "mutation_scope_count": len(mutation_scopes),
            }
        except Exception as error:
            if prepared.effect_overlay is not None:
                prepared.effect_overlay.discard()
            if process is not None:
                terminate_runtime_process(process)
                unregister_runtime_process(session_id, process)
            if output_capture is not None:
                output_capture.wait()
            elif output_handle is not None:
                output_handle.close()
            if output_fd is not None:
                os.close(output_fd)
                output_fd = None
            if output_directory_fd is not None:
                try:
                    os.unlink(output_name, dir_fd=output_directory_fd)
                except FileNotFoundError:
                    pass
            if record is not None:
                transition_runtime_process(
                    self.store,
                    process_id=record.process_id,
                    target_status="failed",
                    failure_reason=(
                        error.reason_code
                        if isinstance(error, RuntimeToolError)
                        else "process_start_failed"
                    ),
                )
            if isinstance(error, RuntimeToolError):
                raise
            raise RuntimeToolError("process_start_failed") from error
        finally:
            if output_directory_fd is not None:
                os.close(output_directory_fd)
            if runtime_fd is not None:
                os.close(runtime_fd)
            prepared.close()

    def status(
        self,
        *,
        process_id: str,
        session_id: str,
        workspace_id: str,
        output_offset: int,
        max_bytes: int,
        execution_control=None,
    ) -> dict[str, object]:
        live = self._owned_live(process_id, session_id, workspace_id)
        with live.lock:
            if execution_control is not None:
                execution_control.check()
            process = live.process
            exit_code = process.poll()
            if exit_code is not None:
                try:
                    self._finish(
                        process_id,
                        live,
                        exit_code=exit_code,
                        execution_control=execution_control,
                    )
                except RuntimeToolError:
                    self._close_live(process_id, live)
                    raise
            size = os.fstat(live.output_fd).st_size
            if output_offset < 0 or output_offset > size:
                raise RuntimeToolError("process_output_offset_invalid")
            requested = min(max_bytes, MAX_PROCESS_STATUS_BYTES)
            output = os.pread(live.output_fd, requested, output_offset)
            next_offset = output_offset + len(output)
            record = self.store.get_process(process_id)
            payload = {
                "process_id": process_id,
                "status": record.status,
                "exit_code": record.exit_code,
                "output": output.decode("utf-8", errors="replace"),
                "output_offset": output_offset,
                "next_output_offset": next_offset,
                "output_pending": next_offset < size,
                "stdin_open": record.stdin_open,
                "failure_reason": record.failure_reason,
                "output_truncated": (
                    live.output_capture.limit_reason == "process_output_too_large"
                ),
                "workspace_effects": live.workspace_effects,
            }
            if record.status != "running" and not payload["output_pending"]:
                self._close_live(process_id, live)
            return payload

    def write_input(
        self,
        *,
        process_id: str,
        session_id: str,
        workspace_id: str,
        content: str,
        close: bool,
    ) -> dict[str, object]:
        payload = content.encode("utf-8")
        if len(payload) > MAX_PROCESS_INPUT_BYTES:
            raise RuntimeToolError("process_input_too_large")
        live = self._owned_live(process_id, session_id, workspace_id)
        with live.lock:
            stream = live.process.stdin
            if stream is None or stream.closed or live.process.poll() is not None:
                raise RuntimeToolError("process_stdin_closed")
            try:
                if payload:
                    stream.write(payload)
                    stream.flush()
                if close:
                    stream.close()
            except (BrokenPipeError, OSError) as error:
                raise RuntimeToolError("process_stdin_closed") from error
            return {
                "process_id": process_id,
                "accepted_bytes": len(payload),
                "stdin_open": not stream.closed,
            }

    def interrupt(
        self,
        *,
        process_id: str,
        session_id: str,
        workspace_id: str,
    ) -> dict[str, object]:
        live = self._owned_live(process_id, session_id, workspace_id)
        with live.lock:
            terminated = self._terminate_live(process_id, live)
            record = self.store.get_process(process_id)
        return {
            "process_id": process_id,
            "status": record.status,
            "terminated": terminated,
        }

    def terminate_session(self, session_id: str) -> int:
        """Terminate and fully finalize every live handle owned by a session."""
        with self._lock:
            owned = tuple(
                (process_id, live)
                for process_id, live in self._live.items()
                if live.session_id == session_id
            )
        finalized: set[str] = set()
        first_error: RuntimeToolError | None = None
        session_processes_alive = True

        # Terminate known leaders first. A SIGTERM trap can create a detached
        # descendant, so an orphan sweep before this phase is not sufficient.
        try:
            for process_id, live in owned:
                try:
                    with live.lock:
                        self._terminate_live(
                            process_id,
                            live,
                            release_handle=False,
                        )
                    finalized.add(process_id)
                except RuntimeToolError as error:
                    first_error = first_error or error
                except Exception:
                    first_error = first_error or RuntimeToolError(
                        "process_session_termination_failed"
                    )
        finally:
            # Always sweep after signalling the known leaders. Retry both the
            # orphan scan and capture finalization within a fixed bound: a
            # detached process may keep the output pipe open until this phase.
            for attempt in range(_SESSION_TERMINATION_SWEEP_ATTEMPTS):
                try:
                    terminate_orphaned_runtime_processes_for_session(
                        session_id,
                        timeout_seconds=(
                            _SESSION_TERMINATION_SWEEP_TIMEOUT_SECONDS
                        ),
                    )
                except Exception:
                    first_error = first_error or RuntimeToolError(
                        "process_session_termination_failed"
                    )
                for process_id, live in owned:
                    if process_id in finalized:
                        continue
                    try:
                        with live.lock:
                            self._terminate_live(
                                process_id,
                                live,
                                release_handle=False,
                            )
                        finalized.add(process_id)
                    except RuntimeToolError as error:
                        first_error = first_error or error
                    except Exception:
                        first_error = first_error or RuntimeToolError(
                            "process_session_termination_failed"
                        )
                try:
                    session_processes_alive = (
                        runtime_processes_alive_for_session(session_id)
                    )
                except Exception:
                    session_processes_alive = True
                    first_error = first_error or RuntimeToolError(
                        "process_session_termination_failed"
                    )
                if len(finalized) == len(owned) and not session_processes_alive:
                    break
                if attempt + 1 < _SESSION_TERMINATION_SWEEP_ATTEMPTS:
                    time.sleep(_SESSION_TERMINATION_SWEEP_PAUSE_SECONDS)

        clean = (
            len(finalized) == len(owned)
            and not session_processes_alive
        )
        if clean:
            with self._lock:
                for process_id, live in owned:
                    if self._live.get(process_id) is live:
                        self._live.pop(process_id, None)
            return len(finalized)
        # Retain every known handle on failure, even if its local resources were
        # already finalized, so a later session cleanup can retry and ownership is
        # never silently lost while a marked descendant remains alive.
        if first_error is not None:
            raise first_error
        raise RuntimeToolError("process_session_termination_incomplete")

    def live_process_count(self, *, session_id: str | None = None) -> int:
        """Return the in-memory live-handle count for lifecycle assertions."""
        with self._lock:
            if session_id is None:
                return len(self._live)
            return sum(
                live.session_id == session_id for live in self._live.values()
            )

    def has_pending_workspace_effects(
        self,
        *,
        process_id: str,
        session_id: str,
        workspace_id: str,
    ) -> bool:
        """Return whether status could cross an unclassified commit boundary."""
        record = self.store.get_process(process_id)
        if record.session_id != session_id or record.workspace_id != workspace_id:
            raise RuntimeToolError("process_not_found")
        with self._lock:
            live = self._live.get(process_id)
        if live is None:
            raise RuntimeToolError("process_handle_unavailable")
        with live.lock:
            return live.effect_overlay is not None

    def _owned_live(
        self,
        process_id: str,
        session_id: str,
        workspace_id: str,
    ) -> _LiveHostedToolProcess:
        record = self.store.get_process(process_id)
        if record.session_id != session_id or record.workspace_id != workspace_id:
            raise RuntimeToolError("process_not_found")
        with self._lock:
            live = self._live.get(process_id)
        if live is None:
            if record.status == "running":
                transition_runtime_process(
                    self.store,
                    process_id=process_id,
                    target_status="failed",
                    failure_reason="process_handle_lost",
                    stdin_open=False,
                    stdout_open=False,
                )
            raise RuntimeToolError("process_handle_unavailable")
        return live

    def _finish(
        self,
        process_id: str,
        live: _LiveHostedToolProcess,
        *,
        exit_code: int,
        execution_control=None,
    ) -> None:
        if not live.output_capture.wait():
            raise RuntimeToolError("process_output_capture_failed")
        record = self.store.get_process(process_id)
        if record.status == "running":
            reason = live.output_capture.limit_reason
            effect_failure: str | None = None
            if live.effect_overlay is not None:
                if reason is None and exit_code == 0:
                    try:
                        live.workspace_effects = (
                            execution_control.run_if_active(
                                live.effect_overlay.commit
                            )
                            if execution_control is not None
                            else live.effect_overlay.commit()
                        )
                    except RuntimeToolError as error:
                        effect_failure = error.reason_code
                        live.workspace_effects = live.effect_overlay.discard()
                else:
                    live.workspace_effects = live.effect_overlay.discard()
            target_status = (
                "timed-out"
                if reason == "process_timed_out"
                else "failed"
                if reason is not None or effect_failure is not None
                else "exited"
            )
            transition_runtime_process(
                self.store,
                process_id=process_id,
                target_status=target_status,
                exit_code=exit_code,
                failure_reason=effect_failure or reason,
                stdin_open=False,
                stdout_open=False,
            )
        else:
            effect_failure = None
        unregister_runtime_process(live.session_id, live.process)
        if live.process.stdin is not None and not live.process.stdin.closed:
            live.process.stdin.close()
        if effect_failure is not None:
            raise RuntimeToolError(effect_failure)

    def _close_live(
        self,
        process_id: str,
        live: _LiveHostedToolProcess,
        *,
        release_handle: bool = True,
    ) -> None:
        if live.process.stdin is not None and not live.process.stdin.closed:
            live.process.stdin.close()
        capture_finished = live.output_capture.wait()
        if live.effect_overlay is not None:
            live.effect_overlay.discard()
        if not capture_finished:
            raise RuntimeToolError("process_output_capture_failed")
        try:
            os.close(live.output_fd)
        except OSError:
            pass
        if release_handle:
            with self._lock:
                if self._live.get(process_id) is live:
                    self._live.pop(process_id, None)

    def _terminate_live(
        self,
        process_id: str,
        live: _LiveHostedToolProcess,
        *,
        release_handle: bool = True,
    ) -> bool:
        terminated = terminate_runtime_process(live.process)
        if live.effect_overlay is not None:
            live.workspace_effects = live.effect_overlay.discard()
        unregister_runtime_process(live.session_id, live.process)
        record = self.store.get_process(process_id)
        if record.status in {"created", "running"}:
            transition_runtime_process(
                self.store,
                process_id=process_id,
                target_status="terminated",
                exit_code=live.process.returncode,
                stdin_open=False,
                stdout_open=False,
            )
        self._close_live(
            process_id,
            live,
            release_handle=release_handle,
        )
        return terminated


def hosted_process_environment(*, session_id: str) -> dict[str, str]:
    """Return the minimal marked environment inherited by process descendants."""
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "MAVERICK_RUNTIME_SESSION_ID": session_id,
        "MAVERICK_RUNTIME_ENGINE_ID": "maverick-hosted-tool-process",
    }


def _redacted_command(argv: list[str]) -> list[str]:
    executable = Path(argv[0]).name
    digest = hashlib.sha256("\0".join(argv).encode("utf-8")).hexdigest()
    return [executable, f"arguments:{max(0, len(argv) - 1)}", f"digest:{digest}"]
