"""Ephemeral core broker for app entrypoint access to app-owned sidecars."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import socketserver
import tempfile
from threading import Lock, Thread
from typing import Any, Callable
from uuid import uuid4

from core.api.sidecar_proxy import (
    AuthorizedSidecarTarget,
    BufferedSidecarResponse,
    request_authorized_sidecar_buffered,
)
from core.apps.models import (
    HttpSidecarEntrypointSurface,
)
from core.apps.sidecar_entrypoint_capabilities import (
    SidecarEntrypointCapabilityBinding,
    SidecarEntrypointCapabilityError,
    SidecarEntrypointCapabilityStore,
)
from core.observability.service import record_platform_audit
from core.shared.entrypoints import (
    EntrypointShutdownController,
)


_PROTOCOL = "maverick.app-sidecar.v1"
_MAX_ENVELOPE_OVERHEAD = 64 * 1024
_ALLOWED_REQUEST_FIELDS = {
    "capability",
    "method",
    "path",
    "query_string",
    "headers",
    "body_base64",
}
BufferedRequestSender = Callable[..., BufferedSidecarResponse]


@dataclass(frozen=True)
class SidecarEntrypointServiceTarget:
    """One already-authorized app sidecar offered to an invocation broker."""

    target: AuthorizedSidecarTarget


class _BrokerUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False


class _BrokerRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        broker: AppSidecarEntrypointBroker = self.server.broker  # type: ignore[attr-defined]
        request = self.rfile.readline(broker.max_request_envelope_bytes + 1)
        if len(request) > broker.max_request_envelope_bytes or not request.endswith(b"\n"):
            response = {"ok": False, "error": "request_envelope_too_large"}
        else:
            response = broker.handle_wire_request(request[:-1])
        self.wfile.write(json.dumps(response, ensure_ascii=True, separators=(",", ":")).encode("utf-8") + b"\n")


class AppSidecarEntrypointBroker:
    """Serve one invocation's capabilities from a private temporary Unix socket."""

    def __init__(
        self,
        *,
        services: list[SidecarEntrypointServiceTarget],
        surface: HttpSidecarEntrypointSurface,
        actor_user_id: str | None,
        runtime_session_id: str | None,
        start_path: Path,
        observability_store=None,
        shutdown_controller: EntrypointShutdownController | None = None,
        request_sender: BufferedRequestSender | None = None,
    ) -> None:
        self.invocation_id = str(uuid4())
        self._services = services
        self._surface = surface
        self._actor_user_id = actor_user_id
        self._runtime_session_id = runtime_session_id
        self._start_path = start_path
        self._observability_store = observability_store
        self._shutdown_controller = shutdown_controller
        self._request_sender = request_sender or request_authorized_sidecar_buffered
        self._capabilities = SidecarEntrypointCapabilityStore()
        self._targets: dict[str, AuthorizedSidecarTarget] = {}
        self._temporary_root: Path | None = None
        self._server: _BrokerUnixServer | None = None
        self._thread: Thread | None = None
        self._close_lock = Lock()
        self._closed = False

    @property
    def max_request_envelope_bytes(self) -> int:
        maximum_body = max(
            (
                target.target.sidecar.entrypoint_access.max_request_body_bytes
                for target in self._services
                if target.target.sidecar.entrypoint_access is not None
            ),
            default=0,
        )
        return (maximum_body * 4 // 3) + _MAX_ENVELOPE_OVERHEAD

    def start(self) -> dict[str, Any] | None:
        """Issue capabilities and start the private socket when the surface is declared."""
        service_specs: list[tuple[AuthorizedSidecarTarget, Any, Any]] = []
        for service in self._services:
            access = service.target.sidecar.entrypoint_access
            if access is None:
                continue
            surface = next((item for item in access.surfaces if item.surface == self._surface), None)
            if surface is not None:
                service_specs.append((service.target, access, surface))
        if not service_specs:
            return None
        first = service_specs[0][0]
        for target, _access, _surface in service_specs[1:]:
            if (
                target.binding.workspace_id != first.binding.workspace_id
                or target.binding.app_id != first.binding.app_id
            ):
                raise ValueError("One entrypoint broker cannot span app or workspace scopes.")
        self._temporary_root = Path(tempfile.mkdtemp(prefix="maverick-entrypoint-sidecar-"))
        os.chmod(self._temporary_root, 0o700)
        socket_path = self._temporary_root / "broker.sock"
        server = _BrokerUnixServer(str(socket_path), _BrokerRequestHandler)
        server.broker = self  # type: ignore[attr-defined]
        os.chmod(socket_path, 0o600)
        self._server = server
        self._thread = Thread(
            target=lambda: server.serve_forever(poll_interval=0.05),
            name=f"app-sidecar-{self.invocation_id}",
            daemon=True,
        )
        self._thread.start()
        descriptors: dict[str, dict[str, Any]] = {}
        for target, access, surface in service_specs:
            service_id = target.sidecar.service_id
            self._targets[service_id] = target
            binding = SidecarEntrypointCapabilityBinding(
                invocation_id=self.invocation_id,
                workspace_id=target.binding.workspace_id,
                app_id=target.binding.app_id,
                service_id=service_id,
                surface=self._surface,
                actor_user_id=self._actor_user_id,
                runtime_session_id=self._runtime_session_id,
                routes=surface.routes,
                ttl_seconds=access.ttl_seconds,
                request_budget=access.request_budget,
                max_request_body_bytes=access.max_request_body_bytes,
                max_response_body_bytes=access.max_response_body_bytes,
            )
            issued = self._capabilities.issue(binding)
            descriptors[service_id] = {
                "broker_socket": str(socket_path),
                "capability": issued.value,
                "expires_in_seconds": issued.expires_in_seconds,
                "request_budget": issued.request_budget,
                "max_request_body_bytes": binding.max_request_body_bytes,
                "max_response_body_bytes": binding.max_response_body_bytes,
                "streaming": False,
            }
            self._record_audit(
                action="sidecar.entrypoint_capability.issue",
                status="succeeded",
                detail="Issued an invocation-scoped app sidecar capability.",
                binding=binding,
                payload={
                    "expires_in_seconds": binding.ttl_seconds,
                    "request_budget": binding.request_budget,
                },
            )
        if self._shutdown_controller is not None:
            self._shutdown_controller.register_cleanup(self.close)
        return {
            "protocol": _PROTOCOL,
            "invocation_id": self.invocation_id,
            "services": descriptors,
        }

    def handle_wire_request(self, wire: bytes) -> dict[str, Any]:
        """Parse, authorize, proxy, and audit one broker request."""
        authorization = None
        try:
            payload = json.loads(wire.decode("utf-8"))
            if not isinstance(payload, dict) or set(payload) - _ALLOWED_REQUEST_FIELDS:
                raise SidecarEntrypointCapabilityError("invalid_request")
            capability = payload.get("capability")
            method = payload.get("method")
            path = payload.get("path")
            query_string = payload.get("query_string", "")
            headers = payload.get("headers", {})
            encoded_body = payload.get("body_base64", "")
            if (
                not isinstance(capability, str)
                or not isinstance(method, str)
                or not isinstance(path, str)
                or not isinstance(query_string, str)
                or not isinstance(headers, dict)
                or not isinstance(encoded_body, str)
            ):
                raise SidecarEntrypointCapabilityError("invalid_request")
            try:
                body = base64.b64decode(encoded_body, validate=True)
            except ValueError as error:
                raise SidecarEntrypointCapabilityError("invalid_request") from error
            authorization = self._capabilities.authorize(
                capability,
                method=method,
                path=path,
                request_body_bytes=len(body),
            )
            binding = authorization.binding
            target = self._targets.get(binding.service_id)
            if target is None:
                raise SidecarEntrypointCapabilityError("service_not_available")
            response = self._request_sender(
                target,
                method=method,
                path=path,
                query_string=query_string,
                headers={str(name): str(value) for name, value in headers.items()},
                body=body,
                max_response_body_bytes=binding.max_response_body_bytes,
                timeout_seconds=binding.ttl_seconds,
                start_path=self._start_path,
                shutdown_controller=self._shutdown_controller,
            )
            if len(response.body) > binding.max_response_body_bytes:
                raise SidecarEntrypointCapabilityError("response_body_too_large")
            self._record_audit(
                action="sidecar.entrypoint_request.proxy",
                status="succeeded" if response.status_code < 400 else "failed",
                detail="Proxied an invocation-scoped app sidecar request.",
                binding=binding,
                payload={
                    "method": str(method).upper(),
                    "response_status": response.status_code,
                    "remaining_requests": authorization.remaining_requests,
                },
            )
            return {
                "ok": True,
                "status_code": response.status_code,
                "headers": response.headers,
                "body_base64": base64.b64encode(response.body).decode("ascii"),
            }
        except SidecarEntrypointCapabilityError as error:
            binding = None if authorization is None else authorization.binding
            self._record_audit(
                action="sidecar.entrypoint_request.deny",
                status="failed",
                detail="Denied an invocation-scoped app sidecar request.",
                binding=binding,
                payload={"reason": error.reason},
            )
            return {"ok": False, "error": error.reason}
        except Exception:
            binding = None if authorization is None else authorization.binding
            self._record_audit(
                action="sidecar.entrypoint_request.proxy",
                status="failed",
                detail="An invocation-scoped app sidecar request failed.",
                binding=binding,
                payload={"reason": "sidecar_request_failed"},
            )
            return {"ok": False, "error": "sidecar_request_failed"}

    def close(self) -> None:
        """Revoke capabilities, stop the socket, and remove its private directory."""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        self._capabilities.revoke_invocation(self.invocation_id)
        for target in self._targets.values():
            access = target.sidecar.entrypoint_access
            if access is None:
                continue
            binding = SidecarEntrypointCapabilityBinding(
                invocation_id=self.invocation_id,
                workspace_id=target.binding.workspace_id,
                app_id=target.binding.app_id,
                service_id=target.sidecar.service_id,
                surface=self._surface,
                actor_user_id=self._actor_user_id,
                runtime_session_id=self._runtime_session_id,
                routes=[],
                ttl_seconds=access.ttl_seconds,
                request_budget=access.request_budget,
                max_request_body_bytes=access.max_request_body_bytes,
                max_response_body_bytes=access.max_response_body_bytes,
            )
            self._record_audit(
                action="sidecar.entrypoint_capability.revoke",
                status="succeeded",
                detail="Revoked an invocation-scoped app sidecar capability.",
                binding=binding,
                payload={},
            )
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self._shutdown_controller is not None:
            self._shutdown_controller.unregister_cleanup(self.close)
        if self._temporary_root is not None:
            shutil.rmtree(self._temporary_root, ignore_errors=True)

    def _record_audit(
        self,
        *,
        action: str,
        status: str,
        detail: str,
        binding: SidecarEntrypointCapabilityBinding | None,
        payload: dict[str, Any],
    ) -> None:
        if self._observability_store is None:
            return
        record_platform_audit(
            self._observability_store,
            action=action,
            status=status,
            source_domain="apps.sidecars.entrypoint",
            detail=detail,
            workspace_id=None if binding is None else binding.workspace_id,
            app_id=None if binding is None else binding.app_id,
            runtime_session_id=None if binding is None else binding.runtime_session_id,
            payload={
                "invocation_id": self.invocation_id,
                "service_id": None if binding is None else binding.service_id,
                "surface": self._surface,
                "actor_user_id": self._actor_user_id,
                **payload,
            },
        )
