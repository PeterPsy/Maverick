"""Supervised, runtime-free execution of native CLI model adapters."""

from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
from threading import Thread
from typing import Iterable

from core.model_access.catalog import resolve_codex_executable
from core.model_access.cancellation import (
    CancellationSignal,
    raise_if_cancelled,
    register_cleanup,
    submission_fence,
)
from core.model_access.cli_sandbox import (
    codex_home_lock as _codex_home_execution_lock,
    codex_sandbox_command as _codex_sandbox_command,
    is_opendesign_connection_probe as _is_opendesign_connection_probe,
    map_sidecar_path as _map_sidecar_path,
    prepare_codex_home as _prepare_codex_home,
    validated_codex_argv as _validated_codex_argv,
)
from core.model_access.models import CliFrame, ModelAccessScope


MAX_CLI_STDIN_BYTES = 32 * 1024 * 1024
class CodexCliExecutor:
    """Launch Codex in an outer filesystem sandbox with no Maverick runtime."""

    def __init__(self, *, repository_root: Path) -> None:
        self.repository_root = Path(repository_root).resolve(strict=True)

    def execute(
        self,
        *,
        scope: ModelAccessScope,
        provider_id: str,
        argv: tuple[str, ...],
        cwd: str,
        stdin: bytes,
        cancellation: CancellationSignal,
    ) -> Iterable[CliFrame]:
        raise_if_cancelled(cancellation)
        if provider_id != "codex" or provider_id not in scope.cli:
            raise PermissionError("CLI provider is not authorized")
        if len(stdin) > MAX_CLI_STDIN_BYTES:
            raise ValueError("CLI input is too large")
        executable = resolve_codex_executable()
        if executable is None:
            raise FileNotFoundError("Codex CLI is unavailable")
        isolated_probe = argv in {("--version",), ("debug", "models"), ("login", "status")}
        connection_probe = _is_opendesign_connection_probe(argv, cwd)
        translated = _validated_codex_argv(
            argv,
            data_root=scope.data_root,
            sidecar_cwd=cwd,
            allow_connection_probe=connection_probe,
        )
        if isolated_probe or connection_probe:
            inner_cwd = "/workspace"
        else:
            _host_cwd, inner_cwd = _map_sidecar_path(scope.data_root, cwd)
        cli_home = _prepare_codex_home(
            self.repository_root,
            scope,
            cancellation=cancellation,
        )
        probe_parent = self.repository_root / "tmp" / "model-access" / "probe-workspaces"
        probe_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if isolated_probe or connection_probe:
            workspace_context = tempfile.TemporaryDirectory(prefix="codex-", dir=probe_parent)
        else:
            workspace_context = _ExistingDirectory(scope.data_root)
        with _codex_home_execution_lock(
            cli_home,
            cancellation=cancellation,
        ), workspace_context as workspace:
            raise_if_cancelled(cancellation)
            command = _codex_sandbox_command(
                executable=executable,
                data_root=Path(workspace),
                inner_cwd=inner_cwd,
                cli_home=cli_home,
                argv=translated,
            )
            process: subprocess.Popen[bytes] | None = None
            writer: Thread | None = None
            selector: selectors.BaseSelector | None = None
            registration = None
            try:
                with submission_fence(cancellation):
                    process = subprocess.Popen(
                        command,
                        cwd="/",
                        env={
                            "CODEX_HOME": "/codex-home",
                            "HOME": "/home/codex",
                            "LANG": "C.UTF-8",
                            "LC_ALL": "C.UTF-8",
                            "PATH": "/usr/local/bin:/usr/bin:/bin",
                            "SSL_CERT_DIR": "/etc/ssl/certs",
                            "SSL_CERT_FILE": "/etc/ssl/certs/ca-certificates.crt",
                            "TMPDIR": "/tmp",
                        },
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        start_new_session=True,
                        bufsize=0,
                    )
                    spawned_process = process
                    registration = register_cleanup(
                        cancellation,
                        lambda: _cancel_process_group(spawned_process),
                    )
                raise_if_cancelled(cancellation)
                assert process.stdin is not None
                assert process.stdout is not None
                assert process.stderr is not None
                writer = Thread(
                    target=_write_stdin,
                    args=(process.stdin, stdin),
                    name="maverick-model-access-codex-stdin",
                    daemon=True,
                )
                writer.start()
                selector = selectors.DefaultSelector()
                selector.register(process.stdout, selectors.EVENT_READ, "stdout")
                selector.register(process.stderr, selectors.EVENT_READ, "stderr")
                while selector.get_map():
                    if cancellation.is_set():
                        _terminate_process_group(process)
                        break
                    for key, _mask in selector.select(timeout=0.1):
                        chunk = os.read(key.fileobj.fileno(), 64 * 1024)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        yield CliFrame(channel=key.data, payload=chunk)
                if cancellation.is_set() and process.poll() is None:
                    _terminate_process_group(process)
                exit_code = process.wait(timeout=10)
            finally:
                if registration is not None:
                    registration.close()
                if selector is not None:
                    selector.close()
                if process is not None and process.poll() is None:
                    _terminate_process_group(process)
                if writer is not None:
                    writer.join(timeout=1)
        yield CliFrame(
            channel="exit",
            payload=json.dumps({"exit_code": exit_code}, separators=(",", ":")).encode("utf-8"),
        )


class _ExistingDirectory:
    """Context adapter matching TemporaryDirectory without owning the path."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def __enter__(self) -> str:
        return str(self.path)

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        return None

def _write_stdin(stream, payload: bytes) -> None:
    try:
        stream.write(payload)
        stream.flush()
    except (BrokenPipeError, OSError):
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=3)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)


def _cancel_process_group(process: subprocess.Popen[bytes]) -> None:
    """Signal immediately; the owning iterator retains bounded reap/escalation."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
