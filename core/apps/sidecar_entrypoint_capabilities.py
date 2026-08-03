"""Invocation-scoped authorization for app-owned HTTP sidecar access."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import secrets
from threading import Lock
import time
from typing import Callable

from core.apps.models import HttpSidecarEntrypointSurface, HttpSidecarRouteRule
from core.apps.sidecar_route_policy import canonicalize_sidecar_path, route_rule_matches


class SidecarEntrypointCapabilityError(RuntimeError):
    """Fail-closed capability denial with a stable redaction-safe reason."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class SidecarEntrypointCapabilityBinding:
    """Trusted scope and limits bound to one app entrypoint invocation."""

    invocation_id: str
    workspace_id: str
    app_id: str
    service_id: str
    surface: HttpSidecarEntrypointSurface
    actor_user_id: str | None
    runtime_session_id: str | None
    routes: list[HttpSidecarRouteRule]
    ttl_seconds: int
    request_budget: int
    max_request_body_bytes: int
    max_response_body_bytes: int


@dataclass(frozen=True)
class IssuedSidecarEntrypointCapability:
    """Opaque capability value delivered only to the invoked app process."""

    value: str
    expires_in_seconds: int
    request_budget: int


@dataclass(frozen=True)
class AuthorizedSidecarEntrypointRequest:
    """Successful capability decision for one bounded HTTP request."""

    binding: SidecarEntrypointCapabilityBinding
    remaining_requests: int


@dataclass
class _CapabilityRecord:
    binding: SidecarEntrypointCapabilityBinding
    expires_at: float
    remaining_requests: int
    revoked: bool = False


class SidecarEntrypointCapabilityStore:
    """Keep only hashed capability values and authorize requests atomically."""

    def __init__(self, *, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._lock = Lock()
        self._records: dict[str, _CapabilityRecord] = {}

    def __repr__(self) -> str:
        with self._lock:
            return f"{type(self).__name__}(record_count={len(self._records)})"

    def issue(self, binding: SidecarEntrypointCapabilityBinding) -> IssuedSidecarEntrypointCapability:
        """Issue one random capability without retaining its raw value."""
        if not 1 <= binding.ttl_seconds <= 30:
            raise ValueError("Entrypoint sidecar capability TTL must be from 1 through 30 seconds.")
        if binding.request_budget <= 0:
            raise ValueError("Entrypoint sidecar capability request budget must be positive.")
        value = secrets.token_urlsafe(32)
        digest = _capability_digest(value)
        with self._lock:
            self._records[digest] = _CapabilityRecord(
                binding=binding,
                expires_at=self._now() + binding.ttl_seconds,
                remaining_requests=binding.request_budget,
            )
        return IssuedSidecarEntrypointCapability(
            value=value,
            expires_in_seconds=binding.ttl_seconds,
            request_budget=binding.request_budget,
        )

    def authorize(
        self,
        value: str,
        *,
        method: str,
        path: str,
        request_body_bytes: int,
        workspace_id: str | None = None,
        app_id: str | None = None,
        service_id: str | None = None,
        surface: str | None = None,
        invocation_id: str | None = None,
    ) -> AuthorizedSidecarEntrypointRequest:
        """Authorize one exact request and consume one unit of its budget."""
        digest = _capability_digest(value)
        normalized_method = str(method or "").strip().upper()
        try:
            canonical_path = canonicalize_sidecar_path(path)
        except ValueError as error:
            raise SidecarEntrypointCapabilityError("path_invalid") from error
        with self._lock:
            record = self._records.get(digest)
            if record is None:
                raise SidecarEntrypointCapabilityError("capability_invalid")
            if record.revoked:
                raise SidecarEntrypointCapabilityError("capability_revoked")
            if self._now() >= record.expires_at:
                raise SidecarEntrypointCapabilityError("capability_expired")
            binding = record.binding
            claimed_scope = {
                "workspace_id": workspace_id,
                "app_id": app_id,
                "service_id": service_id,
                "surface": surface,
                "invocation_id": invocation_id,
            }
            expected_scope = {
                "workspace_id": binding.workspace_id,
                "app_id": binding.app_id,
                "service_id": binding.service_id,
                "surface": binding.surface,
                "invocation_id": binding.invocation_id,
            }
            if any(value is not None and value != expected_scope[key] for key, value in claimed_scope.items()):
                raise SidecarEntrypointCapabilityError("scope_mismatch")
            if request_body_bytes < 0 or request_body_bytes > binding.max_request_body_bytes:
                raise SidecarEntrypointCapabilityError("request_body_too_large")
            if not any(
                route_rule_matches(rule, method=normalized_method, path=canonical_path)
                for rule in binding.routes
            ):
                raise SidecarEntrypointCapabilityError("route_not_allowed")
            if record.remaining_requests <= 0:
                raise SidecarEntrypointCapabilityError("request_budget_exhausted")
            record.remaining_requests -= 1
            return AuthorizedSidecarEntrypointRequest(
                binding=binding,
                remaining_requests=record.remaining_requests,
            )

    def revoke_invocation(self, invocation_id: str) -> int:
        """Revoke every capability bound to one entrypoint invocation."""
        revoked = 0
        with self._lock:
            for record in self._records.values():
                if record.binding.invocation_id == invocation_id and not record.revoked:
                    record.revoked = True
                    revoked += 1
        return revoked

    def contains_raw_value(self, value: str) -> bool:
        """Support a proof that raw capability material is never retained."""
        with self._lock:
            return any(value in repr(record) for record in self._records.values())


def _capability_digest(value: str) -> str:
    if not isinstance(value, str) or not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
