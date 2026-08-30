"""Governed HTTP proxy for app-owned local sidecar services."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import http.client
import logging
import os
from pathlib import Path
from queue import Queue
import re
import secrets
import signal
import socket
import subprocess
from threading import BoundedSemaphore, Event, Lock, Thread
import time
from typing import Any, AsyncIterator, Callable, Iterable, Iterator
from urllib.parse import quote

from core.api.app_registry import resolve_app_surface
from core.api.http import StartResponse, json_response, read_request_body_bytes, status_line
from core.api.platform_state import PlatformState
from core.api.sidecar_core_routes import (
    SidecarCoreRouteContext,
    handle_core_sidecar_route,
    handle_core_sidecar_route_asgi,
)
from core.apps.errors import AppHostingError, WorkspaceAppBindingNotFoundError
from core.apps.artifact_mounts import ResolvedArtifactMount, resolve_artifact_mounts
from core.apps.models import HttpSidecarSpec, ParsedAppContract, WorkspaceAppBindingRecord
from core.apps.lifecycle import run_lifecycle_hook
from core.apps.service_common import _build_workspace_hook_payload
from core.apps.sidecar_host_prepare import run_sidecar_host_prepare
from core.apps.sidecar_route_policy import (
    canonicalize_sidecar_path,
    route_policy_mode,
    validate_asgi_raw_path,
)
from core.apps.sidecar_quarantine import (
    SidecarQuarantineError,
    require_sidecar_not_quarantined,
)
from core.apps.sidecar_execution import (
    ConfinedSidecarLaunch,
    MINIMAL_SIDECAR_ENV,
    prepare_confined_sidecar_launch,
    relay_preamble,
    resolve_sidecar_data_root,
    sandbox_substitutions,
)
from core.authorization.errors import AuthorizationError
from core.authorization.service import can_mount_app_visibility, require_workspace_admin, require_workspace_membership
from core.identity.models import UserRecord
from core.shared.entrypoints import EntrypointShutdownController
from core.shared.repository import discover_repository_root
from core.model_access.broker import issue_model_access_lease
from core.workspaces.paths import workspace_paths


logger = logging.getLogger(__name__)

_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
_DEFAULT_PROXY_TIMEOUT_SECONDS = 60
_PROXY_CHUNK_SIZE = 64 * 1024
_REQUEST_BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_SIDECAR_MANAGER = None
_SIDECAR_SPAWN_LOCK = Lock()
_SIDECAR_SPAWN_QUEUE: Queue["_SidecarSpawnRequest"] = Queue()
_SIDECAR_SPAWN_THREADS: list[Thread] = []
_SIDECAR_SPAWN_WORKER_COUNT = 4
_AUTO_REPAIR_LOCK = Lock()
AutoRepairKey = tuple[str, str, str, str]
_AUTO_REPAIRS: dict[AutoRepairKey, Future[None]] = {}
_AUTO_REPAIR_BACKOFFS: dict[AutoRepairKey, float] = {}
_AUTO_REPAIR_BACKOFF_SECONDS = 60.0
AsgiReceive = Any
AsgiSend = Any


@dataclass(frozen=True)
class _SidecarSpawnRequest:
    """One subprocess creation delegated to the process-lifetime owner thread."""

    command: tuple[str, ...]
    options: dict[str, Any]
    future: Future[subprocess.Popen[bytes]]


def _spawn_sidecar_process(
    command: Iterable[str],
    **options: Any,
) -> subprocess.Popen[bytes]:
    """Spawn from a stable thread so bubblewrap parent-death remains process-scoped.

    Linux parent-death signals follow the thread that called ``fork``.  A
    declarative prewarm runs on a short-lived worker, so invoking ``Popen``
    there would make ``bwrap --die-with-parent`` kill an otherwise healthy
    sidecar as soon as prewarm returned.  A bounded pool of owner threads lives
    for the Core process lifetime, preserving parallel sidecar startups while
    startup and health waits remain outside the global manager lock.
    """
    future: Future[subprocess.Popen[bytes]] = Future()
    _ensure_sidecar_spawn_threads()
    _SIDECAR_SPAWN_QUEUE.put(
        _SidecarSpawnRequest(
            command=tuple(command),
            options=options,
            future=future,
        )
    )
    return future.result()


def _ensure_sidecar_spawn_threads() -> tuple[Thread, ...]:
    with _SIDECAR_SPAWN_LOCK:
        _SIDECAR_SPAWN_THREADS[:] = [
            thread for thread in _SIDECAR_SPAWN_THREADS if thread.is_alive()
        ]
        while len(_SIDECAR_SPAWN_THREADS) < _SIDECAR_SPAWN_WORKER_COUNT:
            thread = Thread(
                target=_sidecar_spawn_worker,
                name=f"maverick-sidecar-process-owner-{len(_SIDECAR_SPAWN_THREADS) + 1}",
                daemon=True,
            )
            _SIDECAR_SPAWN_THREADS.append(thread)
            thread.start()
        return tuple(_SIDECAR_SPAWN_THREADS)


def _sidecar_spawn_worker() -> None:
    while True:
        request = _SIDECAR_SPAWN_QUEUE.get()
        try:
            process = subprocess.Popen(request.command, **request.options)
        except BaseException as error:
            request.future.set_exception(error)
        else:
            request.future.set_result(process)
        finally:
            _SIDECAR_SPAWN_QUEUE.task_done()


@dataclass
class RunningSidecar:
    """One active sidecar process bound to a workspace app."""

    process: subprocess.Popen[bytes]
    host: str
    port: int
    token: str
    instance_id: str
    confined_launch: ConfinedSidecarLaunch
    request_slots: BoundedSemaphore
    stdout_file: Any | None = None
    stderr_file: Any | None = None
    cleanup_callback: Callable[[], None] | None = None
    shutdown_controller: EntrypointShutdownController | None = None
    cleanup_lock: Lock = field(default_factory=Lock)
    cleaned: bool = False


@dataclass
class SidecarStartup:
    """One shared, cancellable startup operation for an exact sidecar key."""

    future: Future[RunningSidecar] = field(default_factory=Future)
    cancel_event: Event = field(default_factory=Event)
    phase: str = "startup_registered"
    started_at: float = field(default_factory=time.monotonic)


class SidecarStartupError(AppHostingError):
    """Typed and redaction-safe sidecar startup failure."""

    def __init__(
        self,
        code: str,
        phase: str,
        detail: str,
        *,
        duration_ms: float = 0.0,
        auto_repairable: bool = False,
        startup_id: str = "",
        difference_count: int = 0,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.phase = phase
        self.duration_ms = max(0.0, round(duration_ms, 3))
        self.auto_repairable = auto_repairable
        self.startup_id = startup_id
        self.difference_count = max(0, difference_count)

    def public_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "code": self.code,
            "phase": self.phase,
            "duration_ms": self.duration_ms,
            "auto_repairable": self.auto_repairable,
        }
        if self.startup_id:
            payload["startup_id"] = self.startup_id
        if self.difference_count:
            payload["difference_count"] = self.difference_count
        return payload


@dataclass(frozen=True)
class SidecarProxyTarget:
    """Validated sidecar proxy request after policy and authorization checks."""

    source_root: Path
    data_root: str
    parsed: ParsedAppContract
    sidecar: HttpSidecarSpec
    proxy_path: str
    route_mode: str


@dataclass(frozen=True)
class AuthorizedSidecarTarget:
    """Sidecar identity authorized for one actor before route selection."""

    binding: WorkspaceAppBindingRecord
    source_root: Path
    parsed: ParsedAppContract
    sidecar: HttpSidecarSpec


@dataclass(frozen=True)
class SidecarProxyError:
    """Small shared error shape for WSGI and ASGI sidecar responses."""

    payload: dict[str, Any]
    status: str


@dataclass(frozen=True)
class BufferedSidecarResponse:
    """One bounded response returned to a core-owned internal broker."""

    status_code: int
    headers: dict[str, str]
    body: bytes


class StreamingSidecarResponse:
    """Iterator that streams an open http.client response and closes it."""

    def __init__(
        self,
        connection: http.client.HTTPConnection,
        response: http.client.HTTPResponse,
        *,
        method: str,
        release_slot: Callable[[], None],
    ) -> None:
        self._connection = connection
        self._response = response
        self._method = method
        self._release_slot = release_slot
        self._closed = False

    def __iter__(self) -> Iterator[bytes]:
        try:
            if self._method == "HEAD":
                return
            while True:
                chunk = self._response.read(_PROXY_CHUNK_SIZE)
                if not chunk:
                    return
                yield chunk
        finally:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._connection.close()
        self._release_slot()


class UnixRelayHTTPConnection(http.client.HTTPConnection):
    """HTTP connection authenticated to a private Unix relay."""

    def __init__(self, running: RunningSidecar, *, timeout: float) -> None:
        super().__init__(running.host, running.port, timeout=timeout)
        self._relay_socket = running.confined_launch.relay_socket
        self._relay_preamble = relay_preamble(running.confined_launch.relay_capability)

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(str(self._relay_socket))
            sock.sendall(self._relay_preamble)
        except OSError:
            sock.close()
            raise
        self.sock = sock


class HttpSidecarManager:
    """Start and reuse app-owned HTTP sidecar processes."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._running: dict[tuple[str, str, str, str], RunningSidecar] = {}
        self._starting: dict[tuple[str, str, str, str], SidecarStartup] = {}
        self._status: dict[tuple[str, str, str, str], dict[str, object]] = {}
        self._quarantined: set[tuple[str, str]] = set()

    def ensure_running(
        self,
        *,
        workspace_id: str,
        app_id: str,
        source_root: Path,
        data_root: str,
        sidecar: HttpSidecarSpec,
        start_path: Path,
        shutdown_controller: EntrypointShutdownController | None,
        verify_existing_health: bool = False,
        host_prepare: Callable[[], dict[str, str]] | None = None,
    ) -> RunningSidecar:
        key = (workspace_id, app_id, sidecar.service_id, data_root)
        stale: RunningSidecar | None = None
        existing: RunningSidecar | None = None
        owner = False
        with self._lock:
            if (workspace_id, app_id) in self._quarantined:
                raise SidecarQuarantineError(
                    f"App `{app_id}` sidecars are quarantined pending operator recovery."
                )
            running = self._running.get(key)
            if running is not None and running.process.poll() is None:
                if not verify_existing_health:
                    return running
                existing = running
            elif running is not None:
                self._running.pop(key, None)
                stale = running
            if existing is None:
                startup = self._starting.get(key)
                if startup is None:
                    startup = SidecarStartup()
                    self._starting[key] = startup
                    self._status[key] = _startup_status_payload(startup, state="starting")
                    owner = True
        if existing is not None:
            return self._verify_existing_sidecar_health(key, existing, sidecar=sidecar)
        if stale is not None:
            self._cleanup_sidecar(stale)
        if not owner:
            return startup.future.result()

        def record_phase(phase: str) -> None:
            with self._lock:
                if self._starting.get(key) is startup:
                    startup.phase = phase
                    self._status[key] = _startup_status_payload(startup, state="starting")

        try:
            running = self._start_sidecar(
                workspace_id=workspace_id,
                app_id=app_id,
                source_root=source_root,
                data_root=data_root,
                sidecar=sidecar,
                start_path=start_path,
                shutdown_controller=shutdown_controller,
                cancel_event=startup.cancel_event,
                record_phase=record_phase,
                host_prepare=host_prepare,
            )
            with self._lock:
                if self._starting.get(key) is not startup or startup.cancel_event.is_set():
                    cancelled = True
                else:
                    cancelled = False
                    self._starting.pop(key, None)
                    self._running[key] = running
                    self._status[key] = {
                        "state": "ready",
                        "phase": "health_ready",
                        "instance_id": running.instance_id,
                        "duration_ms": _startup_elapsed_ms(startup),
                        "updated_at": _utc_timestamp(),
                        "last_failure": None,
                    }
            if cancelled:
                self._cleanup_sidecar(running)
                raise SidecarStartupError(
                    "startup_cancelled",
                    startup.phase,
                    "HTTP sidecar startup was cancelled.",
                    duration_ms=_startup_elapsed_ms(startup),
                )
            startup.future.set_result(running)
            return running
        except Exception as error:
            declared_failure = (
                None
                if startup.cancel_event.is_set()
                else _read_declared_startup_failure(sidecar, data_root=data_root)
            )
            failure = declared_failure or _normalize_startup_error(error, startup=startup)
            with self._lock:
                if self._starting.get(key) is startup:
                    self._starting.pop(key, None)
                self._status[key] = {
                    "state": "failed",
                    "phase": failure.phase,
                    "duration_ms": failure.duration_ms,
                    "updated_at": _utc_timestamp(),
                    "last_failure": failure.public_payload(),
                }
            if not startup.future.done():
                startup.future.set_exception(failure)
            if failure is error:
                raise failure
            raise failure from error

    def _verify_existing_sidecar_health(
        self,
        key: tuple[str, str, str, str],
        running: RunningSidecar,
        *,
        sidecar: HttpSidecarSpec,
    ) -> RunningSidecar:
        try:
            _probe_sidecar_health(running, sidecar=sidecar)
        except SidecarStartupError as failure:
            removed = False
            process_exited = running.process.poll() is not None
            with self._lock:
                if self._running.get(key) is running:
                    if process_exited:
                        self._running.pop(key, None)
                        removed = True
                    self._status[key] = {
                        "state": "failed" if process_exited else "degraded",
                        "phase": failure.phase,
                        "duration_ms": failure.duration_ms,
                        "updated_at": _utc_timestamp(),
                        "last_failure": failure.public_payload(),
                    }
            if removed:
                self._cleanup_sidecar(running)
            raise
        with self._lock:
            if self._running.get(key) is not running or running.process.poll() is not None:
                raise SidecarStartupError(
                    "startup_cancelled",
                    "health_recheck",
                    "HTTP sidecar changed while readiness was being checked.",
                )
            previous = self._status.get(key, {})
            self._status[key] = {
                "state": "ready",
                "phase": "health_recheck",
                "instance_id": running.instance_id,
                "duration_ms": previous.get("duration_ms", 0.0),
                "updated_at": _utc_timestamp(),
                "last_failure": None,
            }
        return running

    def _start_sidecar(
        self,
        *,
        workspace_id: str,
        app_id: str,
        source_root: Path,
        data_root: str,
        sidecar: HttpSidecarSpec,
        start_path: Path,
        shutdown_controller: EntrypointShutdownController | None,
        cancel_event: Event,
        record_phase: Callable[[str], None],
        host_prepare: Callable[[], dict[str, str]] | None,
    ) -> RunningSidecar:
        _raise_if_startup_cancelled(cancel_event, phase="artifact_mount_resolve")
        record_phase("artifact_mount_resolve")
        host = sidecar.bind.host
        port = _allocate_loopback_port(host) if sidecar.bind.port == "auto" else int(sidecar.bind.port)
        token = secrets.token_urlsafe(32)
        workspace = workspace_paths(workspace_id, start_path=start_path)
        repository_root = discover_repository_root(start_path=start_path)
        artifact_mounts = resolve_artifact_mounts(
            repository_root=repository_root,
            app_id=app_id,
            declarations=sidecar.artifact_mounts,
        )
        prepared_environment: dict[str, str] = {}
        if host_prepare is not None:
            _raise_if_startup_cancelled(cancel_event, phase="host_prepare")
            record_phase("host_prepare")
            prepared_environment = host_prepare()
        sidecar_data_root = resolve_sidecar_data_root(
            workspace_root=workspace.root,
            app_id=app_id,
            data_root=Path(data_root),
            sidecar=sidecar,
        )
        _raise_if_startup_cancelled(cancel_event, phase="sandbox_prepare")
        record_phase("sandbox_prepare")
        model_access_lease = None
        if sidecar.model_access is not None:
            try:
                model_access_lease = issue_model_access_lease(
                    repository_root,
                    workspace_id=workspace_id,
                    app_id=app_id,
                    sidecar_id=sidecar.service_id,
                    data_root=sidecar_data_root,
                    api=sidecar.model_access.api,
                    cli=sidecar.model_access.cli,
                )
                if model_access_lease is None and sidecar.model_access.required:
                    raise AppHostingError("Required model access is unavailable.")
            except Exception as error:
                if sidecar.model_access.required:
                    raise AppHostingError("Required model access is unavailable.") from error
                logger.exception(
                    "Optional model access unavailable for app `%s` sidecar `%s`.",
                    app_id,
                    sidecar.service_id,
                )
        stdout_file = None
        stderr_file = None
        try:
            stdout_file = _open_sidecar_log(workspace.root, sidecar.logs.stdout if sidecar.logs else None)
            stderr_file = _open_sidecar_log(workspace.root, sidecar.logs.stderr if sidecar.logs else None)
            env = _sidecar_env(
                workspace_id=workspace_id,
                app_id=app_id,
                data_root=data_root,
                source_root=source_root,
                workspace_root=workspace.root,
                port=port,
                token=token,
                sidecar=sidecar,
                start_path=start_path,
                artifact_mounts=artifact_mounts,
                model_access_lease=model_access_lease,
                host_environment=prepared_environment,
            )
            confined_launch = prepare_confined_sidecar_launch(
                workspace_id=workspace_id,
                app_id=app_id,
                source_root=source_root,
                data_root=Path(data_root),
                workspace_root=workspace.root,
                sidecar=sidecar,
                port=port,
                env=env,
                artifact_mounts=artifact_mounts,
                model_access_directory=(
                    model_access_lease.socket_directory
                    if model_access_lease is not None
                    else None
                ),
                model_access_release=(
                    model_access_lease.release if model_access_lease is not None else None
                ),
            )
        except Exception:
            if model_access_lease is not None:
                model_access_lease.release()
            _close_sidecar_logs(stdout_file, stderr_file)
            raise
        try:
            _raise_if_startup_cancelled(cancel_event, phase="process_spawn")
        except SidecarStartupError:
            confined_launch.cleanup()
            _close_sidecar_logs(stdout_file, stderr_file)
            raise
        record_phase("process_spawn")
        try:
            process = _spawn_sidecar_process(
                confined_launch.command,
                cwd="/",
                env=confined_launch.env,
                stdout=stdout_file or subprocess.DEVNULL,
                stderr=stderr_file or subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                pass_fds=confined_launch.pass_fds,
            )
        except OSError as error:
            confined_launch.cleanup()
            _close_sidecar_logs(stdout_file, stderr_file)
            raise AppHostingError(f"HTTP sidecar `{sidecar.service_id}` failed to start: {error}") from error
        finally:
            confined_launch.close_parent_fds()
        running = RunningSidecar(
            process=process,
            host=host,
            port=port,
            token=token,
            instance_id=secrets.token_urlsafe(18),
            confined_launch=confined_launch,
            request_slots=BoundedSemaphore(sidecar.process_policy.limits.request_concurrency),
            stdout_file=stdout_file,
            stderr_file=stderr_file,
            shutdown_controller=shutdown_controller,
        )
        if shutdown_controller is not None:
            shutdown_controller.register(process)  # type: ignore[arg-type]

            def cleanup_callback() -> None:
                self._cleanup_sidecar(running)

            running.cleanup_callback = cleanup_callback
            shutdown_controller.register_cleanup(cleanup_callback)
        try:
            record_phase("health_wait")
            _wait_for_sidecar_health(running, sidecar=sidecar, cancel_event=cancel_event)
        except AppHostingError:
            self._cleanup_sidecar(running)
            raise
        return running

    def stop_app(self, *, workspace_id: str, app_id: str) -> int:
        """Stop every running sidecar owned by one workspace app."""
        with self._lock:
            keys = [key for key in self._running if key[:2] == (workspace_id, app_id)]
            running_sidecars = [self._running.pop(key) for key in keys]
            for key in keys:
                self._status[key] = {
                    "state": "stopped",
                    "phase": "stop_app",
                    "updated_at": _utc_timestamp(),
                    "last_failure": None,
                }
            startups = [
                startup
                for key, startup in self._starting.items()
                if key[:2] == (workspace_id, app_id)
            ]
            for startup in startups:
                startup.cancel_event.set()
        for running in running_sidecars:
            self._cleanup_sidecar(running)
        for startup in startups:
            try:
                startup.future.result()
            except Exception:
                pass
        return len(running_sidecars) + len(startups)

    def quarantine_app(self, *, workspace_id: str, app_id: str) -> dict[str, object]:
        """Revoke in-process authority first, then attempt bounded process cleanup."""
        with self._lock:
            self._quarantined.add((workspace_id, app_id))
            keys = [key for key in self._running if key[:2] == (workspace_id, app_id)]
            running_sidecars = [self._running.pop(key) for key in keys]
            startup_keys = [
                key for key in self._starting if key[:2] == (workspace_id, app_id)
            ]
            for key in startup_keys:
                self._starting[key].cancel_event.set()
            for key in {*keys, *startup_keys}:
                self._status[key] = {
                    "state": "quarantined",
                    "phase": "core_quarantine",
                    "updated_at": _utc_timestamp(),
                    "last_failure": None,
                }
        stop_confirmed = not startup_keys
        proxy_revoked = True
        for running in running_sidecars:
            revocation = running.confined_launch.revoke_capabilities()
            if revocation.errors:
                logger.error(
                    "Quarantined sidecar capability cleanup was incomplete: %s.",
                    ",".join(revocation.errors),
                )
            try:
                self._cleanup_sidecar(running)
            except Exception:
                logger.exception("Quarantined sidecar process cleanup did not complete.")
                stop_confirmed = False
            else:
                stop_confirmed = stop_confirmed and running.process.poll() is not None
            proxy_revoked = (
                proxy_revoked
                and running.confined_launch.relay_is_revoked()
            )
        return {
            "proxy_revoked": proxy_revoked,
            "writer_stop_confirmed": stop_confirmed,
            "affected_service_count": len(running_sidecars) + len(startup_keys),
        }

    def release_quarantine(self, *, workspace_id: str, app_id: str) -> None:
        """Open only the in-process gate; no sidecar is started implicitly."""
        with self._lock:
            self._quarantined.discard((workspace_id, app_id))

    def startup_status(
        self,
        *,
        workspace_id: str,
        app_id: str,
        sidecar_id: str,
        data_root: str,
    ) -> dict[str, object]:
        """Return the latest redaction-safe lifecycle state without starting a sidecar."""
        key = (workspace_id, app_id, sidecar_id, data_root)
        stale: RunningSidecar | None = None
        with self._lock:
            running = self._running.get(key)
            if running is not None and running.process.poll() is not None:
                self._running.pop(key, None)
                stale = running
                failure = SidecarStartupError(
                    "daemon_spawn_failed",
                    "health_status",
                    "HTTP sidecar exited after startup.",
                )
                self._status[key] = {
                    "state": "failed",
                    "phase": failure.phase,
                    "updated_at": _utc_timestamp(),
                    "last_failure": failure.public_payload(),
                }
            status = dict(self._status.get(key, {"state": "not_started", "phase": "idle"}))
        if stale is not None:
            self._cleanup_sidecar(stale)
        return status

    def current_instance_id(
        self,
        *,
        workspace_id: str,
        app_id: str,
        sidecar_id: str,
        data_root: str,
    ) -> str | None:
        """Return the live process identity without starting or restarting it."""
        key = (workspace_id, app_id, sidecar_id, data_root)
        with self._lock:
            running = self._running.get(key)
            if running is None or running.process.poll() is not None:
                return None
            return running.instance_id

    def _cleanup_sidecar(self, running: RunningSidecar) -> None:
        with running.cleanup_lock:
            if running.cleaned:
                return
            process = running.process
            if process.poll() is None:
                _signal_process_group(process, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    _signal_process_group(process, signal.SIGKILL)
                    process.wait(timeout=5)
            if running.shutdown_controller is not None:
                running.shutdown_controller.unregister(process)  # type: ignore[arg-type]
                if running.cleanup_callback is not None:
                    running.shutdown_controller.unregister_cleanup(running.cleanup_callback)
            running.confined_launch.cleanup()
            _close_sidecar_logs(running.stdout_file, running.stderr_file)
            running.cleaned = True


def stop_app_sidecars(*, workspace_id: str, app_id: str) -> int:
    """Stop an app's live sidecars without creating a manager as a side effect."""
    manager = _SIDECAR_MANAGER
    if manager is not None:
        return manager.stop_app(workspace_id=workspace_id, app_id=app_id)
    return 0


def quarantine_app_sidecars(*, workspace_id: str, app_id: str) -> dict[str, object]:
    """Fence live proxy authority even when process termination cannot be proven."""
    manager = _sidecar_manager()
    return manager.quarantine_app(workspace_id=workspace_id, app_id=app_id)


def release_app_sidecar_quarantine(*, workspace_id: str, app_id: str) -> None:
    """Release the in-memory half of an explicitly cleared durable fence."""
    manager = _SIDECAR_MANAGER
    if manager is not None:
        manager.release_quarantine(workspace_id=workspace_id, app_id=app_id)


def app_sidecar_startup_status(
    *,
    workspace_id: str,
    app_id: str,
    sidecar_id: str,
    data_root: str,
) -> dict[str, object]:
    """Read live manager state without creating or starting a sidecar."""
    manager = _SIDECAR_MANAGER
    if manager is None:
        return {"state": "not_started", "phase": "idle"}
    return manager.startup_status(
        workspace_id=workspace_id,
        app_id=app_id,
        sidecar_id=sidecar_id,
        data_root=data_root,
    )


def app_sidecar_current_instance_id(
    *,
    workspace_id: str,
    app_id: str,
    sidecar_id: str,
    data_root: str,
) -> str | None:
    """Return one live manager instance identity without starting a sidecar."""
    manager = _SIDECAR_MANAGER
    if manager is None:
        return None
    return manager.current_instance_id(
        workspace_id=workspace_id,
        app_id=app_id,
        sidecar_id=sidecar_id,
        data_root=data_root,
    )


def sidecar_error_payload(error: AppHostingError, *, default_code: str) -> dict[str, object]:
    """Return a bounded startup diagnostic without leaking runtime inputs or paths."""
    if isinstance(error, SidecarStartupError):
        return {"error": error.code, **error.public_payload()}
    return {
        "error": default_code,
        "code": default_code,
        "phase": "sidecar",
        "auto_repairable": False,
    }


def restart_declared_app_sidecars(
    *,
    workspace_id: str,
    app_id: str,
    source_root: Path,
    data_root: str,
    sidecars: Iterable[HttpSidecarSpec],
    start_path: Path,
    shutdown_controller: EntrypointShutdownController | None = None,
    binding: WorkspaceAppBindingRecord | None = None,
    parsed: ParsedAppContract | None = None,
) -> dict[str, object]:
    """Restart exactly one app's declared sidecars and wait for declared health checks."""
    declared = tuple(sidecars)
    if not declared:
        raise AppHostingError(f"App `{app_id}` does not declare HTTP sidecars.")
    manager = _sidecar_manager()
    stopped = manager.stop_app(workspace_id=workspace_id, app_id=app_id)
    started: list[dict[str, str]] = []
    try:
        for sidecar in declared:
            if sidecar.host_prepare is not None:
                if binding is None or parsed is None:
                    raise AppHostingError(
                        "Sidecar host preparation requires its resolved workspace binding."
                    )
                running = ensure_sidecar_with_declared_auto_repair(
                    binding=binding,
                    source_root=source_root,
                    parsed=parsed,
                    sidecar=sidecar,
                    start_path=start_path,
                    shutdown_controller=shutdown_controller,
                )
            else:
                running = manager.ensure_running(
                    workspace_id=workspace_id,
                    app_id=app_id,
                    source_root=source_root,
                    data_root=data_root,
                    sidecar=sidecar,
                    start_path=start_path,
                    shutdown_controller=shutdown_controller,
                )
            started.append(
                {
                    "service_id": sidecar.service_id,
                    "instance_id": running.instance_id,
                }
            )
    except Exception:
        manager.stop_app(workspace_id=workspace_id, app_id=app_id)
        raise
    return {
        "ready": True,
        "stopped_service_count": stopped,
        "service_count": len(started),
        "services": started,
    }


def handle_app_sidecar_proxy(
    state: PlatformState,
    *,
    environ: dict,
    workspace_id: str,
    app_id: str,
    sidecar_id: str,
    subpath: str,
    user: UserRecord | None,
    start_path: Path,
    start_response: StartResponse,
    shutdown_controller: EntrypointShutdownController | None = None,
) -> Iterable[bytes]:
    """Proxy one request to a declared app-owned HTTP sidecar."""
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    target, error = _resolve_sidecar_proxy_target(
        state,
        workspace_id=workspace_id,
        app_id=app_id,
        sidecar_id=sidecar_id,
        subpath=subpath,
        user=user,
        method=method,
        start_path=start_path,
    )
    if error is not None:
        return json_response(start_response, error.payload, status=error.status)
    assert target is not None
    try:
        if target.route_mode == "handled_by_core":
            return handle_core_sidecar_route(
                state,
                environ=environ,
                workspace_id=workspace_id,
                app_id=app_id,
                user=user,
                context=_core_route_context(target),
                start_path=start_path,
                start_response=start_response,
                shutdown_controller=shutdown_controller,
                logger=logger,
            )
        body = read_request_body_bytes(environ)
        running = _sidecar_manager().ensure_running(
            workspace_id=workspace_id,
            app_id=app_id,
            source_root=target.source_root,
            data_root=target.data_root,
            sidecar=target.sidecar,
            start_path=start_path,
            shutdown_controller=shutdown_controller,
        )
        return _proxy_to_running_sidecar(
            running,
            method=method,
            path=target.proxy_path,
            query_string=str(environ.get("QUERY_STRING") or ""),
            environ=environ,
            body=body,
            start_response=start_response,
        )
    except AppHostingError as error:
        logger.warning("App `%s` sidecar `%s` unavailable: %s", app_id, sidecar_id, error)
        return json_response(
            start_response,
            sidecar_error_payload(error, default_code="sidecar_unavailable"),
            status="503 Service Unavailable",
        )
    except Exception:
        logger.exception("App `%s` sidecar `%s` proxy failed.", app_id, sidecar_id)
        return json_response(start_response, {"error": "sidecar_proxy_failed"}, status="502 Bad Gateway")


async def handle_app_sidecar_proxy_asgi(
    state: PlatformState,
    *,
    scope: dict[str, Any],
    receive: AsgiReceive,
    send: AsgiSend,
    workspace_id: str,
    app_id: str,
    sidecar_id: str,
    subpath: str,
    user: UserRecord | None,
    start_path: Path,
    shutdown_controller: EntrypointShutdownController | None = None,
    enforced_response_headers: list[tuple[str, str]] | None = None,
    expected_instance_id: str | None = None,
) -> None:
    """Proxy one ASGI request to a declared sidecar without pre-buffering the body."""
    method = str(scope.get("method") or "GET").upper()
    try:
        validate_asgi_raw_path(path=scope.get("path"), raw_path=scope.get("raw_path"))
    except ValueError:
        await _send_asgi_json(
            send,
            {"error": "sidecar_path_invalid"},
            status="400 Bad Request",
            headers=enforced_response_headers,
        )
        return
    target, error = _resolve_sidecar_proxy_target(
        state,
        workspace_id=workspace_id,
        app_id=app_id,
        sidecar_id=sidecar_id,
        subpath=subpath,
        user=user,
        method=method,
        start_path=start_path,
    )
    if error is not None:
        await _send_asgi_json(send, error.payload, status=error.status, headers=enforced_response_headers)
        return
    assert target is not None
    try:
        if target.route_mode == "handled_by_core":
            await handle_core_sidecar_route_asgi(
                state,
                scope=scope,
                receive=receive,
                send=send,
                workspace_id=workspace_id,
                app_id=app_id,
                user=user,
                context=_core_route_context(target),
                start_path=start_path,
                shutdown_controller=shutdown_controller,
                logger=logger,
                response_headers=enforced_response_headers,
            )
            return
        running = await asyncio.to_thread(
            _sidecar_manager().ensure_running,
            workspace_id=workspace_id,
            app_id=app_id,
            source_root=target.source_root,
            data_root=target.data_root,
            sidecar=target.sidecar,
            start_path=start_path,
            shutdown_controller=shutdown_controller,
        )
        if expected_instance_id is not None and running.instance_id != expected_instance_id:
            await _send_asgi_json(
                send,
                {"error": "sidecar_session_stale"},
                status="401 Unauthorized",
                headers=enforced_response_headers,
            )
            return
        await _proxy_asgi_to_running_sidecar(
            running,
            method=method,
            path=target.proxy_path,
            query_string=bytes(scope.get("query_string") or b"").decode("latin1"),
            scope=scope,
            sidecar=target.sidecar,
            receive=receive,
            send=send,
            enforced_response_headers=enforced_response_headers,
        )
    except AppHostingError as error:
        logger.warning("App `%s` sidecar `%s` unavailable: %s", app_id, sidecar_id, error)
        await _send_asgi_json(
            send,
            sidecar_error_payload(error, default_code="sidecar_unavailable"),
            status="503 Service Unavailable",
            headers=enforced_response_headers,
        )
    except Exception:
        logger.exception("App `%s` sidecar `%s` ASGI proxy failed.", app_id, sidecar_id)
        await _send_asgi_json(
            send,
            {"error": "sidecar_proxy_failed"},
            status="502 Bad Gateway",
            headers=enforced_response_headers,
        )


def parse_app_sidecar_proxy_route(path: object) -> tuple[str, str, str] | None:
    """Parse the generic app sidecar proxy route."""
    text = str(path or "")
    if not text.startswith("/api/apps/"):
        return None
    remainder = text.removeprefix("/api/apps/")
    app_id, separator, rest = remainder.partition("/sidecars/")
    if not separator or not app_id or "/" in app_id or not rest:
        return None
    sidecar_id, _separator, subpath = rest.partition("/")
    if not sidecar_id or "/" in sidecar_id:
        return None
    return app_id, sidecar_id, subpath


def _sidecar_manager() -> HttpSidecarManager:
    global _SIDECAR_MANAGER
    if _SIDECAR_MANAGER is None:
        _SIDECAR_MANAGER = HttpSidecarManager()
    return _SIDECAR_MANAGER


def _resolve_sidecar_proxy_target(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    sidecar_id: str,
    subpath: str,
    user: UserRecord | None,
    method: str,
    start_path: Path,
) -> tuple[SidecarProxyTarget | None, SidecarProxyError | None]:
    authorized, error = resolve_authorized_sidecar(
        state,
        workspace_id=workspace_id,
        app_id=app_id,
        sidecar_id=sidecar_id,
        user=user,
        start_path=start_path,
    )
    if error is not None:
        return None, error
    assert authorized is not None
    binding = authorized.binding
    source_root = authorized.source_root
    parsed = authorized.parsed
    sidecar = authorized.sidecar
    try:
        proxy_path = _proxy_path(subpath)
    except ValueError:
        return None, SidecarProxyError({"error": "sidecar_path_invalid"}, "400 Bad Request")
    route_mode = _route_mode(sidecar, method=method, path=proxy_path)
    if route_mode == "blocked":
        return None, SidecarProxyError(
            {"error": "sidecar_route_blocked", "sidecar_id": sidecar.service_id},
            "403 Forbidden",
        )
    if route_mode not in {"handled_by_core", "pass_through"}:
        return None, SidecarProxyError(
            {"error": "sidecar_route_not_allowed", "sidecar_id": sidecar.service_id},
            "404 Not Found",
        )
    return SidecarProxyTarget(
        source_root=source_root,
        data_root=binding.data_root,
        parsed=parsed,
        sidecar=sidecar,
        proxy_path=proxy_path,
        route_mode=route_mode,
    ), None


def resolve_authorized_sidecar(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    sidecar_id: str,
    user: UserRecord | None,
    start_path: Path,
) -> tuple[AuthorizedSidecarTarget | None, SidecarProxyError | None]:
    """Resolve one sidecar and actor without granting any route."""
    if user is None:
        return None, SidecarProxyError({"error": "authentication_required"}, "401 Unauthorized")
    try:
        require_sidecar_not_quarantined(
            state.app_store,
            workspace_id=workspace_id,
            app_id=app_id,
        )
    except SidecarQuarantineError:
        return None, SidecarProxyError(
            {"error": "sidecar_quarantined"},
            "503 Service Unavailable",
        )
    try:
        binding, source_root, parsed = resolve_app_surface(
            state,
            workspace_id=workspace_id,
            app_id=app_id,
            start_path=start_path,
        )
    except WorkspaceAppBindingNotFoundError:
        return None, SidecarProxyError({"error": "app_not_installed"}, "404 Not Found")
    except AppHostingError:
        return None, SidecarProxyError({"error": "app_unavailable"}, "404 Not Found")
    try:
        require_workspace_membership(state.workspace_store, user=user, workspace_id=workspace_id)
    except AuthorizationError:
        return None, SidecarProxyError({"error": "workspace_not_available"}, "403 Forbidden")
    if binding.source_kind == "workspace_local_project":
        try:
            require_workspace_admin(
                state.workspace_store,
                user=user,
                workspace_id=workspace_id,
                reason="workspace_local_sidecar_forbidden",
            )
        except AuthorizationError as error:
            return None, SidecarProxyError({"error": error.reason}, "403 Forbidden")
    if not can_mount_app_visibility(
        state.workspace_store,
        user=user,
        workspace_id=workspace_id,
        platform_roles=parsed.contract.visibility.platform_roles,
        workspace_roles=parsed.contract.visibility.workspace_roles,
        capabilities=parsed.contract.visibility.capabilities,
    ):
        return None, SidecarProxyError({"error": "app_forbidden"}, "403 Forbidden")
    sidecar = _find_sidecar(parsed.contract.services.http_sidecars, sidecar_id)
    if sidecar is None or sidecar.proxy is None:
        return None, SidecarProxyError({"error": "sidecar_not_found"}, "404 Not Found")
    return AuthorizedSidecarTarget(
        binding=binding,
        source_root=source_root,
        parsed=parsed,
        sidecar=sidecar,
    ), None


def ensure_authorized_sidecar_running(
    target: AuthorizedSidecarTarget,
    *,
    start_path: Path,
    shutdown_controller: EntrypointShutdownController | None,
    verify_existing_health: bool = False,
) -> RunningSidecar:
    """Start or reuse an already-authorized sidecar for browser bootstrap."""
    return ensure_sidecar_with_declared_auto_repair(
        binding=target.binding,
        source_root=target.source_root,
        parsed=target.parsed,
        sidecar=target.sidecar,
        start_path=start_path,
        shutdown_controller=shutdown_controller,
        verify_existing_health=verify_existing_health,
    )


def ensure_sidecar_with_declared_auto_repair(
    *,
    binding: WorkspaceAppBindingRecord,
    source_root: Path,
    parsed: ParsedAppContract,
    sidecar: HttpSidecarSpec,
    start_path: Path,
    shutdown_controller: EntrypointShutdownController | None,
    verify_existing_health: bool = False,
) -> RunningSidecar:
    """Start a sidecar and perform at most one declared, singleflight repair."""
    manager = _sidecar_manager()
    host_prepare = _sidecar_host_prepare_callback(
        binding=binding,
        source_root=source_root,
        sidecar=sidecar,
        start_path=start_path,
    )
    try:
        return manager.ensure_running(
            workspace_id=binding.workspace_id,
            app_id=binding.app_id,
            source_root=source_root,
            data_root=binding.data_root,
            sidecar=sidecar,
            start_path=start_path,
            shutdown_controller=shutdown_controller,
            verify_existing_health=verify_existing_health,
            host_prepare=host_prepare,
        )
    except SidecarStartupError as error:
        if not error.auto_repairable or "artifact_repair" not in parsed.contract.entrypoints.hooks:
            raise
        repair_key = _run_declared_artifact_repair_singleflight(
            binding=binding,
            source_root=source_root,
            parsed=parsed,
            sidecar=sidecar,
            start_path=start_path,
        )
    try:
        running = manager.ensure_running(
            workspace_id=binding.workspace_id,
            app_id=binding.app_id,
            source_root=source_root,
            data_root=binding.data_root,
            sidecar=sidecar,
            start_path=start_path,
            shutdown_controller=shutdown_controller,
            verify_existing_health=verify_existing_health,
            host_prepare=host_prepare,
        )
    except SidecarStartupError as error:
        _record_auto_repair_validation_failure(repair_key)
        raise SidecarStartupError(
            "artifact_repair_failed",
            "artifact_repair_validation",
            "The repaired sidecar did not pass its transactional startup gate.",
            duration_ms=error.duration_ms,
            startup_id=error.startup_id,
            difference_count=error.difference_count,
        ) from error
    _complete_auto_repair_validation(repair_key)
    return running


def _sidecar_host_prepare_callback(
    *,
    binding: WorkspaceAppBindingRecord,
    source_root: Path,
    sidecar: HttpSidecarSpec,
    start_path: Path,
) -> Callable[[], dict[str, str]] | None:
    declaration = sidecar.host_prepare
    if declaration is None:
        return None
    payload = _build_workspace_hook_payload(
        workspace_id=binding.workspace_id,
        app_id=binding.app_id,
        data_root=Path(binding.data_root),
        source_kind=binding.source_kind,
        source_record_id=binding.source_record_id,
        hook_name="sidecar_host_prepare",
        start_path=start_path,
    )
    payload.update(
        {
            "sidecar_id": sidecar.service_id,
            "managed_writer_stopped": True,
        }
    )
    return lambda: run_sidecar_host_prepare(
        source_root,
        declaration,
        payload=payload,
    )


def _run_declared_artifact_repair_singleflight(
    *,
    binding: WorkspaceAppBindingRecord,
    source_root: Path,
    parsed: ParsedAppContract,
    sidecar: HttpSidecarSpec,
    start_path: Path,
) -> AutoRepairKey:
    key = (
        binding.workspace_id,
        binding.app_id,
        sidecar.service_id,
        str(binding.data_root),
    )
    owner = False
    with _AUTO_REPAIR_LOCK:
        future = _AUTO_REPAIRS.get(key)
        if future is None:
            retry_after = _AUTO_REPAIR_BACKOFFS.get(key, 0.0)
            if retry_after > time.monotonic():
                raise SidecarStartupError(
                    "artifact_repair_failed",
                    "artifact_repair_backoff",
                    "Declared artifact repair is in bounded backoff.",
                )
            future = Future()
            _AUTO_REPAIRS[key] = future
            _AUTO_REPAIR_BACKOFFS[key] = time.monotonic() + _AUTO_REPAIR_BACKOFF_SECONDS
            owner = True
    if not owner:
        future.result()
        return key
    try:
        payload = _build_workspace_hook_payload(
            workspace_id=binding.workspace_id,
            app_id=binding.app_id,
            data_root=Path(binding.data_root),
            source_kind=binding.source_kind,
            source_record_id=binding.source_record_id,
            hook_name="artifact_repair",
            start_path=start_path,
        )
        run_lifecycle_hook(
            source_root,
            parsed.contract,
            hook_name="artifact_repair",
            payload=payload,
        )
    except Exception as error:
        failure = SidecarStartupError(
            "artifact_repair_failed",
            "artifact_repair",
            "Declared artifact repair failed.",
        )
        with _AUTO_REPAIR_LOCK:
            _AUTO_REPAIR_BACKOFFS[key] = time.monotonic() + _AUTO_REPAIR_BACKOFF_SECONDS
        future.set_exception(failure)
        raise failure from error
    else:
        with _AUTO_REPAIR_LOCK:
            # Keep the gate closed until the repaired daemon passes transactional startup.
            _AUTO_REPAIR_BACKOFFS[key] = time.monotonic() + _AUTO_REPAIR_BACKOFF_SECONDS
        future.set_result(None)
    finally:
        with _AUTO_REPAIR_LOCK:
            if _AUTO_REPAIRS.get(key) is future:
                _AUTO_REPAIRS.pop(key, None)
    return key


def _record_auto_repair_validation_failure(key: AutoRepairKey) -> None:
    with _AUTO_REPAIR_LOCK:
        _AUTO_REPAIR_BACKOFFS[key] = time.monotonic() + _AUTO_REPAIR_BACKOFF_SECONDS


def _complete_auto_repair_validation(key: AutoRepairKey) -> None:
    with _AUTO_REPAIR_LOCK:
        _AUTO_REPAIR_BACKOFFS.pop(key, None)


def current_sidecar_instance_id(target: AuthorizedSidecarTarget) -> str | None:
    """Return the current process identity for session restart validation."""
    return _sidecar_manager().current_instance_id(
        workspace_id=target.binding.workspace_id,
        app_id=target.binding.app_id,
        sidecar_id=target.sidecar.service_id,
        data_root=target.binding.data_root,
    )


def request_authorized_sidecar_buffered(
    target: AuthorizedSidecarTarget,
    *,
    method: str,
    path: str,
    query_string: str,
    headers: dict[str, str],
    body: bytes,
    max_response_body_bytes: int,
    timeout_seconds: float,
    start_path: Path,
    shutdown_controller: EntrypointShutdownController | None,
) -> BufferedSidecarResponse:
    """Send one bounded pass-through request without exposing technical transport details."""
    normalized_method = str(method or "").strip().upper()
    canonical_path = canonicalize_sidecar_path(path)
    if target.sidecar.proxy is None or route_policy_mode(
        target.sidecar.proxy.route_policy,
        method=normalized_method,
        path=canonical_path,
    ) != "pass_through":
        raise AppHostingError("HTTP sidecar route is not authorized for pass-through.")
    if len(query_string) > 8192 or any(character in query_string for character in ("\r", "\n", "#")):
        raise AppHostingError("HTTP sidecar query string is invalid.")
    running = ensure_authorized_sidecar_running(
        target,
        start_path=start_path,
        shutdown_controller=shutdown_controller,
    )
    if not running.request_slots.acquire(blocking=False):
        raise AppHostingError("HTTP sidecar request concurrency limit reached.")
    connection = UnixRelayHTTPConnection(running, timeout=max(0.1, min(timeout_seconds, 30.0)))
    forwarded_headers: dict[str, str] = {}
    for raw_name, raw_value in headers.items():
        name = str(raw_name).strip().replace("_", "-").title()
        value = str(raw_value).strip()
        lowered = name.lower()
        if (
            not name
            or any(character in name + value for character in ("\r", "\n"))
            or lowered in _HOP_BY_HOP_HEADERS
            or lowered in {"host", "cookie", "authorization", "content-length"}
        ):
            continue
        forwarded_headers[name] = value
    forwarded_headers["Authorization"] = f"Bearer {running.token}"
    if body:
        forwarded_headers["Content-Length"] = str(len(body))
    upstream_path = quote(canonical_path, safe="/:@-._~!$&'()*+,;=")
    if query_string:
        upstream_path = f"{upstream_path}?{query_string}"
    try:
        connection.request(
            normalized_method,
            upstream_path,
            body=body if body else None,
            headers=forwarded_headers,
        )
        response = connection.getresponse()
        response_body = response.read(max_response_body_bytes + 1)
        if len(response_body) > max_response_body_bytes:
            raise AppHostingError("HTTP sidecar response exceeded the entrypoint capability limit.")
        response_headers = {
            name.lower(): value
            for name, value in _forward_response_headers(response.getheaders())
        }
        return BufferedSidecarResponse(
            status_code=response.status,
            headers=response_headers,
            body=response_body,
        )
    except (OSError, http.client.HTTPException) as error:
        raise AppHostingError("HTTP sidecar is not reachable.") from error
    finally:
        connection.close()
        running.request_slots.release()


def _find_sidecar(sidecars: list[HttpSidecarSpec], sidecar_id: str) -> HttpSidecarSpec | None:
    for sidecar in sidecars:
        if sidecar.service_id == sidecar_id:
            return sidecar
    return None


def _route_mode(sidecar: HttpSidecarSpec, *, method: str, path: str) -> str:
    assert sidecar.proxy is not None
    return route_policy_mode(sidecar.proxy.route_policy, method=method, path=path)


def _proxy_path(subpath: str) -> str:
    canonical = canonicalize_sidecar_path(subpath)
    return quote(canonical, safe="/:@-._~!$&'()*+,;=")


def _core_route_context(target: SidecarProxyTarget) -> SidecarCoreRouteContext:
    return SidecarCoreRouteContext(
        source_root=target.source_root,
        data_root=target.data_root,
        parsed=target.parsed,
        sidecar=target.sidecar,
        proxy_path=target.proxy_path,
    )


def _proxy_to_running_sidecar(
    running: RunningSidecar,
    *,
    method: str,
    path: str,
    query_string: str,
    environ: dict,
    body: bytes,
    start_response: StartResponse,
) -> Iterable[bytes]:
    upstream_path = f"{path}?{query_string}" if query_string else path
    if not running.request_slots.acquire(blocking=False):
        raise AppHostingError("HTTP sidecar request concurrency limit reached.")
    connection = UnixRelayHTTPConnection(running, timeout=_DEFAULT_PROXY_TIMEOUT_SECONDS)
    headers = _forward_request_headers(environ)
    headers["Authorization"] = f"Bearer {running.token}"
    if body:
        headers["Content-Length"] = str(len(body))
    try:
        connection.request(method, upstream_path, body=body if body else None, headers=headers)
        response = connection.getresponse()
    except (OSError, http.client.HTTPException) as error:
        connection.close()
        running.request_slots.release()
        raise AppHostingError("HTTP sidecar is not reachable.") from error
    try:
        response_headers = _forward_response_headers(response.getheaders())
        start_response(
            f"{response.status} {response.reason or status_line(response.status).split(' ', 1)[1]}",
            response_headers,
        )
    except Exception:
        connection.close()
        running.request_slots.release()
        raise
    return StreamingSidecarResponse(
        connection,
        response,
        method=method,
        release_slot=running.request_slots.release,
    )


async def _proxy_asgi_to_running_sidecar(
    running: RunningSidecar,
    *,
    method: str,
    path: str,
    query_string: str,
    scope: dict[str, Any],
    sidecar: HttpSidecarSpec,
    receive: AsgiReceive,
    send: AsgiSend,
    enforced_response_headers: list[tuple[str, str]] | None,
) -> None:
    upstream_path = f"{path}?{query_string}" if query_string else path
    if not running.request_slots.acquire(blocking=False):
        raise AppHostingError("HTTP sidecar request concurrency limit reached.")
    writer: asyncio.StreamWriter | None = None
    response_started = False
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(str(running.confined_launch.relay_socket)),
            timeout=_DEFAULT_PROXY_TIMEOUT_SECONDS,
        )
        writer.write(relay_preamble(running.confined_launch.relay_capability))
        await writer.drain()
        request_headers = _forward_asgi_request_headers(scope)
        stream_request_as_chunked = method in _REQUEST_BODY_METHODS and not _asgi_header_present(scope, "content-length")
        request_headers["Host"] = f"{running.host}:{running.port}"
        request_headers["Authorization"] = f"Bearer {running.token}"
        request_headers["Connection"] = "close"
        if method in _REQUEST_BODY_METHODS:
            request_headers["Origin"] = f"http://{running.host}:{running.port}"
            request_headers["Sec-Fetch-Site"] = "same-origin"
        if stream_request_as_chunked:
            request_headers["Transfer-Encoding"] = "chunked"
        header_lines = [f"{method} {upstream_path} HTTP/1.1"]
        header_lines.extend(f"{name}: {value}" for name, value in request_headers.items())
        header_lines.append("")
        header_lines.append("")
        writer.write("\r\n".join(header_lines).encode("latin1"))
        await writer.drain()
        await _stream_asgi_request_body(receive, writer, chunked=stream_request_as_chunked)
        response_status, _response_reason, response_headers = await _read_asgi_upstream_response_head(reader)
        _ensure_asgi_response_allowed_by_contract(sidecar, response_headers)
        forwarded_headers = _merge_response_headers(
            _forward_asgi_response_headers(response_headers),
            enforced_response_headers,
        )
        await send(
            {
                "type": "http.response.start",
                "status": response_status,
                "headers": [
                    (name.lower().encode("latin1"), value.encode("latin1"))
                    for name, value in forwarded_headers
                ],
            }
        )
        response_started = True
        if method != "HEAD":
            async for chunk in _stream_asgi_upstream_response_body(reader, response_headers):
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
    except OSError as error:
        if not response_started:
            raise AppHostingError("HTTP sidecar is not reachable.") from error
        logger.warning("HTTP sidecar stream ended with a socket error.", exc_info=True)
    except Exception:
        if not response_started:
            raise
        logger.warning("HTTP sidecar stream ended with an upstream protocol error.", exc_info=True)
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
        running.request_slots.release()
    await send({"type": "http.response.body", "body": b"", "more_body": False})


async def _stream_asgi_request_body(receive: AsgiReceive, writer: asyncio.StreamWriter, *, chunked: bool) -> None:
    while True:
        message = await receive()
        if message.get("type") != "http.request":
            if chunked:
                writer.write(b"0\r\n\r\n")
                await writer.drain()
            return
        chunk = bytes(message.get("body") or b"")
        if chunk:
            if chunked:
                writer.write(f"{len(chunk):x}\r\n".encode("ascii"))
                writer.write(chunk)
                writer.write(b"\r\n")
            else:
                writer.write(chunk)
            await writer.drain()
        if not message.get("more_body", False):
            if chunked:
                writer.write(b"0\r\n\r\n")
                await writer.drain()
            return


async def _read_asgi_upstream_response_head(reader: asyncio.StreamReader) -> tuple[int, str, list[tuple[str, str]]]:
    status_line_bytes = await asyncio.wait_for(reader.readline(), timeout=_DEFAULT_PROXY_TIMEOUT_SECONDS)
    if not status_line_bytes:
        raise AppHostingError("HTTP sidecar closed before sending a response.")
    try:
        status_parts = status_line_bytes.decode("latin1").rstrip("\r\n").split(" ", 2)
        status_code = int(status_parts[1])
        reason = status_parts[2] if len(status_parts) > 2 else ""
    except (UnicodeDecodeError, ValueError, IndexError) as error:
        raise AppHostingError("HTTP sidecar returned an invalid HTTP response.") from error
    headers: list[tuple[str, str]] = []
    while True:
        line = await asyncio.wait_for(reader.readline(), timeout=_DEFAULT_PROXY_TIMEOUT_SECONDS)
        if line in {b"\r\n", b"\n", b""}:
            break
        try:
            name, value = line.decode("latin1").rstrip("\r\n").split(":", 1)
        except ValueError as error:
            raise AppHostingError("HTTP sidecar returned an invalid HTTP header.") from error
        headers.append((name.strip(), value.strip()))
    return status_code, reason, headers


async def _stream_asgi_upstream_response_body(
    reader: asyncio.StreamReader,
    headers: list[tuple[str, str]],
) -> AsyncIterator[bytes]:
    lowered = {name.lower(): value for name, value in headers}
    transfer_encoding = lowered.get("transfer-encoding", "").lower()
    content_length = lowered.get("content-length")
    if "chunked" in transfer_encoding:
        async for chunk in _stream_chunked_asgi_body(reader):
            yield chunk
        return
    if content_length is not None:
        try:
            remaining = int(content_length)
        except ValueError as error:
            raise AppHostingError("HTTP sidecar returned an invalid Content-Length header.") from error
        while remaining > 0:
            chunk = await asyncio.wait_for(
                reader.read(min(_PROXY_CHUNK_SIZE, remaining)),
                timeout=_DEFAULT_PROXY_TIMEOUT_SECONDS,
            )
            if not chunk:
                return
            remaining -= len(chunk)
            yield chunk
        return
    while True:
        chunk = await asyncio.wait_for(reader.read(_PROXY_CHUNK_SIZE), timeout=_DEFAULT_PROXY_TIMEOUT_SECONDS)
        if not chunk:
            return
        yield chunk


async def _stream_chunked_asgi_body(reader: asyncio.StreamReader) -> AsyncIterator[bytes]:
    while True:
        size_line = await asyncio.wait_for(reader.readline(), timeout=_DEFAULT_PROXY_TIMEOUT_SECONDS)
        if not size_line:
            return
        size_text = size_line.decode("latin1").strip().split(";", 1)[0]
        try:
            size = int(size_text, 16)
        except ValueError as error:
            raise AppHostingError("HTTP sidecar returned an invalid chunked response.") from error
        if size == 0:
            await _discard_chunked_trailers(reader)
            return
        remaining = size
        while remaining > 0:
            chunk = await asyncio.wait_for(
                reader.read(min(_PROXY_CHUNK_SIZE, remaining)),
                timeout=_DEFAULT_PROXY_TIMEOUT_SECONDS,
            )
            if not chunk:
                return
            remaining -= len(chunk)
            yield chunk
        await asyncio.wait_for(reader.readexactly(2), timeout=_DEFAULT_PROXY_TIMEOUT_SECONDS)


async def _discard_chunked_trailers(reader: asyncio.StreamReader) -> None:
    while True:
        line = await asyncio.wait_for(reader.readline(), timeout=_DEFAULT_PROXY_TIMEOUT_SECONDS)
        if line in {b"\r\n", b"\n", b""}:
            return


def _ensure_asgi_response_allowed_by_contract(sidecar: HttpSidecarSpec, headers: list[tuple[str, str]]) -> None:
    if sidecar.proxy is None:
        return
    content_type = ""
    for name, value in headers:
        if name.lower() == "content-type":
            content_type = value.split(";", 1)[0].strip().lower()
            break
    if content_type == "text/event-stream" and not sidecar.proxy.sse:
        raise AppHostingError("HTTP sidecar returned SSE without declaring `proxy.sse` support.")


def _forward_request_headers(environ: dict) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in environ.items():
        if not key.startswith("HTTP_"):
            continue
        name = key.removeprefix("HTTP_").replace("_", "-").title()
        if name.lower() in _HOP_BY_HOP_HEADERS or name.lower() in {"host", "cookie", "authorization"}:
            continue
        headers[name] = str(value)
    if environ.get("CONTENT_TYPE"):
        headers["Content-Type"] = str(environ["CONTENT_TYPE"])
    return headers


def _forward_response_headers(headers: list[tuple[str, str]]) -> list[tuple[str, str]]:
    forwarded: list[tuple[str, str]] = []
    for name, value in headers:
        lowered = name.lower()
        if lowered in _HOP_BY_HOP_HEADERS or lowered in {"authorization", "set-cookie"}:
            continue
        if lowered == "location" and not _safe_redirect_location(value):
            continue
        forwarded.append((name, value))
    return forwarded


def _forward_asgi_request_headers(scope: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw_name, raw_value in scope.get("headers", []):
        name = raw_name.decode("latin1").replace("_", "-").title()
        lowered = name.lower()
        if lowered in _HOP_BY_HOP_HEADERS or lowered in {"host", "cookie", "authorization"}:
            continue
        headers[name] = raw_value.decode("latin1")
    return headers


def _asgi_header_present(scope: dict[str, Any], header_name: str) -> bool:
    expected = header_name.lower().encode("latin1")
    return any(raw_name.lower() == expected for raw_name, _raw_value in scope.get("headers", []))


def _forward_asgi_response_headers(headers: list[tuple[str, str]]) -> list[tuple[str, str]]:
    forwarded: list[tuple[str, str]] = []
    for name, value in headers:
        lowered = name.lower()
        if lowered in _HOP_BY_HOP_HEADERS or lowered in {"authorization", "set-cookie"}:
            continue
        if lowered == "location" and not _safe_redirect_location(value):
            continue
        forwarded.append((name, value))
    return forwarded


def _safe_redirect_location(value: str) -> bool:
    return value.startswith("/") and not value.startswith("//") and "\\" not in value and not any(
        ord(character) < 32 for character in value
    )


def _merge_response_headers(
    headers: list[tuple[str, str]],
    enforced: list[tuple[str, str]] | None,
) -> list[tuple[str, str]]:
    if not enforced:
        return headers
    enforced_names = {name.lower() for name, _value in enforced}
    return [(name, value) for name, value in headers if name.lower() not in enforced_names] + list(enforced)


async def _send_asgi_json(
    send: AsgiSend,
    payload: dict[str, Any],
    *,
    status: str,
    headers: list[tuple[str, str]] | None = None,
) -> None:
    body = json.dumps(payload, indent=2).encode("utf-8")
    status_code = int(status.split(" ", 1)[0])
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
                *[(name.lower().encode("latin1"), value.encode("latin1")) for name, value in (headers or [])],
            ],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


def _allocate_loopback_port(host: str) -> int:
    family = socket.AF_INET6 if host == "::1" else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _open_sidecar_log(workspace_root: Path, relative_path: str | None):
    if not relative_path:
        return None
    path = (workspace_root / relative_path).resolve()
    root = workspace_root.resolve()
    if root != path and root not in path.parents:
        raise AppHostingError("Sidecar log path escapes workspace root.")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("ab")


def _close_sidecar_logs(*files: Any | None) -> None:
    seen: set[int] = set()
    for file_obj in files:
        if file_obj is None or id(file_obj) in seen:
            continue
        seen.add(id(file_obj))
        try:
            file_obj.close()
        except OSError:
            pass


def _sidecar_env(
    *,
    workspace_id: str,
    app_id: str,
    data_root: str,
    source_root: Path,
    workspace_root: Path,
    port: int,
    token: str,
    sidecar: HttpSidecarSpec,
    start_path: Path,
    artifact_mounts: tuple[ResolvedArtifactMount, ...] = (),
    model_access_lease=None,
    host_environment: dict[str, str] | None = None,
) -> dict[str, str]:
    del data_root, source_root, workspace_root, start_path
    env = dict(MINIMAL_SIDECAR_ENV)
    substitutions = sandbox_substitutions(port=port, token=token, artifact_mounts=artifact_mounts)
    for key, value in sidecar.env.items():
        env[key] = _replace_substitutions(value, substitutions)
    prepared = host_environment or {}
    if set(prepared) & set(env):
        raise AppHostingError("Sidecar host preparation attempted to replace static environment.")
    env.update(prepared)
    env["MAVERICK_APP_ID"] = app_id
    env["MAVERICK_WORKSPACE_ID"] = workspace_id
    env["MAVERICK_SIDECAR_ID"] = sidecar.service_id
    env["MAVERICK_SIDECAR_PORT"] = str(port)
    if sidecar.model_access is not None:
        env["MAVERICK_MODEL_ACCESS_STATE"] = (
            "available" if model_access_lease is not None else "unavailable"
        )
        if model_access_lease is not None:
            env["MAVERICK_MODEL_ACCESS_SOCKET"] = model_access_lease.sandbox_socket_path
            env["MAVERICK_MODEL_ACCESS_TOKEN"] = model_access_lease.token
    return env


def _replace_substitutions(value: str, substitutions: dict[str, str]) -> str:
    result = value
    for token, replacement in substitutions.items():
        result = result.replace(token, replacement)
    if "${" in result:
        raise AppHostingError("HTTP sidecar environment contains an unsupported substitution.")
    return result


def _wait_for_sidecar_health(
    running: RunningSidecar,
    *,
    sidecar: HttpSidecarSpec,
    cancel_event: Event | None = None,
) -> None:
    deadline = time.monotonic() + (sidecar.health.timeout_ms / 1000)
    last_error = "not ready"
    while time.monotonic() < deadline:
        if cancel_event is not None and cancel_event.is_set():
            raise SidecarStartupError(
                "startup_cancelled",
                "health_wait",
                "HTTP sidecar startup was cancelled.",
            )
        if running.process.poll() is not None:
            raise SidecarStartupError(
                "daemon_spawn_failed",
                "health_wait",
                f"HTTP sidecar exited with code {running.process.returncode}.",
            )
        connection = UnixRelayHTTPConnection(running, timeout=1.5)
        try:
            connection.request(
                "GET",
                sidecar.health.path,
                headers={
                    "Authorization": f"Bearer {running.token}",
                    "Connection": "close",
                    "Host": f"{running.host}:{running.port}",
                },
            )
            response = connection.getresponse()
            if 200 <= response.status < 300:
                return
            last_error = f"health returned HTTP {response.status}"
        except (OSError, http.client.HTTPException) as error:
            last_error = str(error)
        finally:
            connection.close()
        if cancel_event is None:
            time.sleep(0.1)
        else:
            cancel_event.wait(0.1)
    raise SidecarStartupError(
        "daemon_ready_timeout",
        "health_wait",
        f"HTTP sidecar `{sidecar.service_id}` did not become ready: {last_error}",
    )


def _probe_sidecar_health(running: RunningSidecar, *, sidecar: HttpSidecarSpec) -> None:
    """Revalidate transactional readiness before granting fresh authority."""
    started = time.monotonic()
    if running.process.poll() is not None:
        raise SidecarStartupError(
            "daemon_spawn_failed",
            "health_recheck",
            "HTTP sidecar exited before its readiness recheck.",
            duration_ms=(time.monotonic() - started) * 1000,
        )
    connection = UnixRelayHTTPConnection(running, timeout=0.75)
    try:
        connection.request(
            "GET",
            sidecar.health.path,
            headers={
                "Authorization": f"Bearer {running.token}",
                "Connection": "close",
                "Host": f"{running.host}:{running.port}",
            },
        )
        response = connection.getresponse()
        response.read(65_537)
    except (OSError, http.client.HTTPException) as error:
        raise SidecarStartupError(
            "daemon_ready_timeout",
            "health_recheck",
            "HTTP sidecar readiness recheck failed.",
            duration_ms=(time.monotonic() - started) * 1000,
        ) from error
    finally:
        connection.close()
    if not 200 <= response.status < 300:
        raise SidecarStartupError(
            "activation_incomplete",
            "health_recheck",
            "HTTP sidecar is not transactionally ready.",
            duration_ms=(time.monotonic() - started) * 1000,
        )


def _raise_if_startup_cancelled(cancel_event: Event, *, phase: str) -> None:
    if cancel_event.is_set():
        raise SidecarStartupError(
            "startup_cancelled",
            phase,
            "HTTP sidecar startup was cancelled.",
        )


def _normalize_startup_error(error: Exception, *, startup: SidecarStartup) -> SidecarStartupError:
    duration_ms = _startup_elapsed_ms(startup)
    if isinstance(error, SidecarStartupError):
        if error.duration_ms:
            return error
        return SidecarStartupError(
            error.code,
            error.phase,
            str(error),
            duration_ms=duration_ms,
            auto_repairable=error.auto_repairable,
            startup_id=error.startup_id,
            difference_count=error.difference_count,
        )
    detail = str(error)
    if startup.phase == "artifact_mount_resolve":
        lowered = detail.lower()
        code = "artifact_permissions_invalid" if any(
            fragment in lowered for fragment in ("protection", "protected", "ownership", "read-only")
        ) else "artifact_missing"
    elif startup.phase == "sandbox_prepare":
        code = "runtime_binding_invalid"
    elif startup.phase == "process_spawn":
        code = "daemon_spawn_failed"
    else:
        code = "daemon_ready_timeout"
    return SidecarStartupError(
        code,
        startup.phase,
        detail or "HTTP sidecar startup failed.",
        duration_ms=duration_ms,
        auto_repairable=code in {"artifact_missing", "artifact_integrity_mismatch"},
    )


def _startup_status_payload(startup: SidecarStartup, *, state: str) -> dict[str, object]:
    return {
        "state": state,
        "phase": startup.phase,
        "duration_ms": _startup_elapsed_ms(startup),
        "updated_at": _utc_timestamp(),
        "last_failure": None,
    }


def _read_declared_startup_failure(sidecar: HttpSidecarSpec, *, data_root: str) -> SidecarStartupError | None:
    declaration = sidecar.diagnostics
    if declaration is None:
        return None
    root = Path(data_root)
    try:
        root = root.resolve(strict=True)
        path = root.joinpath(*declaration.status_file.split("/"))
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        metadata = path.lstat()
        if path.is_symlink() or not path.is_file() or metadata.st_size > 64 * 1024:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    failure = payload.get("last_failure") if isinstance(payload, dict) else None
    if payload.get("schema_version") != "3" or not isinstance(failure, dict):
        return None
    code = failure.get("code")
    phase = failure.get("phase")
    startup_id = failure.get("startup_id")
    duration = failure.get("duration_ms")
    differences = failure.get("difference_count", 0)
    if (
        not isinstance(code, str)
        or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) is None
        or not isinstance(phase, str)
        or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", phase) is None
        or not isinstance(startup_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", startup_id) is None
        or isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or isinstance(differences, bool)
        or not isinstance(differences, int)
    ):
        return None
    return SidecarStartupError(
        code,
        phase,
        f"HTTP sidecar startup failed during {phase}.",
        duration_ms=float(duration),
        auto_repairable=failure.get("auto_repairable") is True,
        startup_id=startup_id,
        difference_count=differences,
    )


def _startup_elapsed_ms(startup: SidecarStartup) -> float:
    return round((time.monotonic() - startup.started_at) * 1000, 3)


def _utc_timestamp() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def _signal_process_group(process: subprocess.Popen[bytes], signum: signal.Signals) -> None:
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        return
    except OSError:
        if process.poll() is None:
            if signum == signal.SIGKILL:
                process.kill()
            else:
                process.terminate()
