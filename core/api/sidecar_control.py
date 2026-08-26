"""Owner-authenticated local control channel for the live Core sidecar manager."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import stat
import struct
from threading import Lock, Thread, current_thread
from typing import Any

from core.api.sidecar_prewarm import prewarm_workspace_app_sidecars
from core.api.sidecar_proxy import app_sidecar_startup_status, stop_app_sidecars
from core.apps.errors import AppHostingError
from core.apps.sidecar_restart import restart_workspace_app_sidecars
from core.apps.surfaces import resolve_workspace_app_surface


_MAX_MESSAGE_BYTES = 64 * 1024
_SERVERS_LOCK = Lock()
_SERVERS: dict[Path, Thread] = {}


class SidecarControlError(AppHostingError):
    """Typed failure returned by the live Core control channel."""

    def __init__(self, code: str, phase: str) -> None:
        super().__init__("Live Maverick sidecar control failed.")
        self.code = code
        self.phase = phase


def sidecar_control_socket_path(repository_root: Path) -> Path:
    repository = Path(repository_root).resolve(strict=True)
    configured = os.environ.get("MAVERICK_SIDECAR_CONTROL_SOCKET", "").strip()
    path = Path(configured) if configured else repository / "tmp/maverick-sidecar-control.sock"
    if not path.is_absolute():
        raise SidecarControlError("runtime_binding_invalid", "sidecar_control_resolve")
    return path


def start_sidecar_control_server(state, *, shutdown_controller) -> Thread | None:
    """Start one live-process Unix control server, deduplicated by socket path."""
    path = sidecar_control_socket_path(state.repository_root)
    with _SERVERS_LOCK:
        existing = _SERVERS.get(path)
        if existing is not None and existing.is_alive():
            return existing
        thread = Thread(
            target=_serve,
            kwargs={"state": state, "path": path, "shutdown_controller": shutdown_controller},
            name="maverick-sidecar-control",
            daemon=True,
        )
        _SERVERS[path] = thread
        thread.start()
        return thread


def request_sidecar_control(
    repository_root: Path,
    *,
    operation: str,
    workspace_id: str,
    app_id: str,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Invoke the manager owned by the running Core process, never a CLI-local copy."""
    request = {
        "schema_version": "1",
        "operation": operation,
        "workspace_id": workspace_id,
        "app_id": app_id,
    }
    body = (json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    path = sidecar_control_socket_path(repository_root)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout_seconds)
    try:
        client.connect(str(path))
        client.sendall(body)
        client.shutdown(socket.SHUT_WR)
        response = _receive_bounded(client)
    except (OSError, TimeoutError) as error:
        raise SidecarControlError("daemon_spawn_failed", "sidecar_control_connect") from error
    finally:
        client.close()
    try:
        payload = json.loads(response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SidecarControlError("runtime_binding_invalid", "sidecar_control_response") from error
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        code = str(payload.get("error_code") or "daemon_spawn_failed") if isinstance(payload, dict) else "daemon_spawn_failed"
        phase = str(payload.get("phase") or "sidecar_control") if isinstance(payload, dict) else "sidecar_control"
        raise SidecarControlError(code, phase)
    result = payload.get("result")
    if not isinstance(result, dict):
        raise SidecarControlError("runtime_binding_invalid", "sidecar_control_response")
    return result


def _serve(*, state, path: Path, shutdown_controller) -> None:
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.exists() or path.is_symlink():
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.geteuid():
                return
            path.unlink()
        server.bind(str(path))
        path.chmod(0o600)
        server.listen(8)
        server.settimeout(0.25)
        while not shutdown_controller.is_shutting_down():
            try:
                connection, _address = server.accept()
            except socket.timeout:
                continue
            with connection:
                try:
                    _handle_connection(
                        connection,
                        state=state,
                        shutdown_controller=shutdown_controller,
                    )
                except OSError:
                    continue
    finally:
        server.close()
        try:
            if path.exists() and not path.is_symlink() and stat.S_ISSOCK(path.lstat().st_mode):
                path.unlink()
        except OSError:
            pass
        with _SERVERS_LOCK:
            if _SERVERS.get(path) is current_thread():
                _SERVERS.pop(path, None)


def _handle_connection(connection: socket.socket, *, state, shutdown_controller) -> None:
    try:
        if _peer_uid(connection) != os.geteuid():
            raise SidecarControlError("runtime_binding_invalid", "sidecar_control_peer")
        request = json.loads(_receive_bounded(connection).decode("utf-8"))
        result = _dispatch(request, state=state, shutdown_controller=shutdown_controller)
        response = {"ok": True, "result": result}
    except Exception as error:
        response = {
            "ok": False,
            "error_code": getattr(error, "code", "daemon_spawn_failed"),
            "phase": getattr(error, "phase", "sidecar_control"),
        }
    connection.sendall((json.dumps(response, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def _dispatch(request: object, *, state, shutdown_controller) -> dict[str, Any]:
    expected = {"schema_version", "operation", "workspace_id", "app_id"}
    if not isinstance(request, dict) or set(request) != expected or request.get("schema_version") != "1":
        raise SidecarControlError("runtime_binding_invalid", "sidecar_control_request")
    operation = str(request.get("operation") or "")
    workspace_id = _identifier(request.get("workspace_id"))
    app_id = _identifier(request.get("app_id"))
    if operation == "prewarm":
        binding = state.app_store.get_workspace_app_binding(
            workspace_id=workspace_id,
            app_id=app_id,
        )
        return prewarm_workspace_app_sidecars(
            state,
            binding=binding,
            trigger="activation",
            shutdown_controller=shutdown_controller,
        )
    if operation == "stop":
        state.sidecar_browser_sessions.revoke_app(
            workspace_id=workspace_id,
            app_id=app_id,
        )
        stopped = stop_app_sidecars(workspace_id=workspace_id, app_id=app_id)
        return {
            "ready": False,
            "browser_sessions_revoked": True,
            "stopped_service_count": stopped,
        }
    if operation == "status":
        binding = state.app_store.get_workspace_app_binding(
            workspace_id=workspace_id,
            app_id=app_id,
        )
        _source_root, parsed = resolve_workspace_app_surface(
            state.app_store,
            binding=binding,
            start_path=state.repository_root,
        )
        return {
            "workspace_id": workspace_id,
            "app_id": app_id,
            "services": [
                {
                    "sidecar_id": sidecar.service_id,
                    **app_sidecar_startup_status(
                        workspace_id=workspace_id,
                        app_id=app_id,
                        sidecar_id=sidecar.service_id,
                        data_root=binding.data_root,
                    ),
                }
                for sidecar in parsed.contract.services.http_sidecars
            ],
        }
    if operation == "restart":
        return restart_workspace_app_sidecars(
            state.app_store,
            workspace_id=workspace_id,
            app_id=app_id,
            sidecar_browser_sessions=state.sidecar_browser_sessions,
            start_path=state.repository_root,
            app_event_bus=state.app_event_bus,
            observability_store=state.observability_store,
            shutdown_controller=shutdown_controller,
        )
    raise SidecarControlError("runtime_binding_invalid", "sidecar_control_request")


def _identifier(value: object) -> str:
    text = str(value or "")
    if not text or len(text) > 128 or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in text):
        raise SidecarControlError("runtime_binding_invalid", "sidecar_control_request")
    return text


def _receive_bounded(connection: socket.socket) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = connection.recv(min(8192, _MAX_MESSAGE_BYTES + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > _MAX_MESSAGE_BYTES:
            raise SidecarControlError("runtime_binding_invalid", "sidecar_control_request")
    return b"".join(chunks)


def _peer_uid(connection: socket.socket) -> int:
    option = getattr(socket, "SO_PEERCRED", None)
    if option is None:
        return os.geteuid()
    credentials = connection.getsockopt(socket.SOL_SOCKET, option, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", credentials)
    return uid
