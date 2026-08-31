"""Hashed one-shot tickets and host-bound sessions for sidecar browser origins."""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import secrets
from threading import Lock
import time
from typing import Callable


SIDECAR_BROWSER_COOKIE_NAME = "maverick_sidecar_session"
SIDECAR_BROWSER_RESOURCE_COOKIE_NAME = "__Host-maverick_sidecar_resource_session"
MAX_TICKET_TTL_SECONDS = 30
BOOTSTRAP_CONFIRMATION_TTL_SECONDS = 30
SESSION_IDLE_TTL_SECONDS = 5 * 60
SESSION_ABSOLUTE_TTL_SECONDS = 60 * 60
SESSION_ROTATION_SECONDS = 60
SESSION_ROTATION_GRACE_SECONDS = 10


@dataclass(frozen=True)
class SidecarBrowserBinding:
    """Authority bound to one browser ticket and its resulting session."""

    actor_user_id: str
    workspace_id: str
    app_id: str
    sidecar_id: str
    host: str
    origin: str
    platform_origin: str
    generation_id: str
    sidecar_instance_id: str
    clean_path: str
    secure: bool
    content_security_policy: str


@dataclass(frozen=True)
class IssuedSidecarBrowserTicket:
    """Raw one-shot value returned only to the authenticated launch caller."""

    value: str
    confirmation_value: str
    expires_at: float
    binding: SidecarBrowserBinding


@dataclass(frozen=True)
class SidecarBrowserSession:
    """Hashed browser-session state retained by core."""

    token_digest: str
    binding: SidecarBrowserBinding
    created_at: float
    last_seen_at: float
    rotated_at: float
    idle_expires_at: float
    absolute_expires_at: float


@dataclass(frozen=True)
class IssuedSidecarBrowserSession:
    """New session value issued by bootstrap."""

    value: str
    session: SidecarBrowserSession


@dataclass(frozen=True)
class ValidatedSidecarBrowserSession:
    """Live session plus an optional rotated cookie value."""

    session: SidecarBrowserSession
    rotated_value: str | None


@dataclass(frozen=True)
class _TicketRecord:
    token_digest: str
    confirmation_digest: str
    binding: SidecarBrowserBinding
    expires_at: float


@dataclass(frozen=True)
class _BootstrapConfirmationRecord:
    token_digest: str
    binding: SidecarBrowserBinding
    expires_at: float
    confirmed: bool


class SidecarBrowserSessionStore:
    """Thread-safe in-process authority; restart revokes every live secret."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = Lock()
        self._tickets: dict[str, _TicketRecord] = {}
        self._confirmations: dict[str, _BootstrapConfirmationRecord] = {}
        self._sessions: dict[str, SidecarBrowserSession] = {}
        self._session_confirmations: dict[str, str] = {}
        self._aliases: dict[str, tuple[str, float]] = {}

    def issue_ticket(
        self,
        binding: SidecarBrowserBinding,
        *,
        ttl_seconds: int = MAX_TICKET_TTL_SECONDS,
    ) -> IssuedSidecarBrowserTicket:
        if not 1 <= ttl_seconds <= MAX_TICKET_TTL_SECONDS:
            raise ValueError("Sidecar browser ticket TTL exceeds the allowed bound.")
        now = self._clock()
        value = secrets.token_urlsafe(32)
        digest = _token_digest(value)
        confirmation_value = secrets.token_urlsafe(32)
        confirmation_digest = _token_digest(confirmation_value)
        expires_at = now + ttl_seconds
        with self._lock:
            self._prune(now)
            self._tickets[digest] = _TicketRecord(
                token_digest=digest,
                confirmation_digest=confirmation_digest,
                binding=binding,
                expires_at=expires_at,
            )
            self._confirmations[confirmation_digest] = _BootstrapConfirmationRecord(
                token_digest=confirmation_digest,
                binding=binding,
                expires_at=expires_at,
                confirmed=False,
            )
        return IssuedSidecarBrowserTicket(
            value=value,
            confirmation_value=confirmation_value,
            expires_at=expires_at,
            binding=binding,
        )

    def consume_ticket(self, value: str, *, host: str) -> IssuedSidecarBrowserSession | None:
        now = self._clock()
        digest = _token_digest(value)
        with self._lock:
            self._prune(now)
            ticket = self._tickets.pop(digest, None)
            if ticket is None or ticket.expires_at < now or not secrets.compare_digest(ticket.binding.host, host):
                if ticket is not None:
                    self._confirmations.pop(ticket.confirmation_digest, None)
                return None
            session_value = secrets.token_urlsafe(32)
            session_digest = _token_digest(session_value)
            session = SidecarBrowserSession(
                token_digest=session_digest,
                binding=ticket.binding,
                created_at=now,
                last_seen_at=now,
                rotated_at=now,
                idle_expires_at=now + SESSION_IDLE_TTL_SECONDS,
                absolute_expires_at=now + SESSION_ABSOLUTE_TTL_SECONDS,
            )
            self._sessions[session_digest] = session
            self._session_confirmations[session_digest] = ticket.confirmation_digest
            return IssuedSidecarBrowserSession(value=session_value, session=session)

    def confirm_bootstrap(self, session: SidecarBrowserSession) -> bool:
        """Confirm only a live session created by a successfully validated bootstrap."""
        now = self._clock()
        with self._lock:
            self._prune(now)
            current = self._sessions.get(session.token_digest)
            confirmation_digest = self._session_confirmations.get(session.token_digest)
            if current != session or confirmation_digest is None:
                return False
            confirmation = self._confirmations.get(confirmation_digest)
            if confirmation is None or confirmation.binding != session.binding:
                return False
            self._confirmations[confirmation_digest] = replace(
                confirmation,
                confirmed=True,
                expires_at=now + BOOTSTRAP_CONFIRMATION_TTL_SECONDS,
            )
            return True

    def bootstrap_confirmation_status(
        self,
        value: str,
        *,
        actor_user_id: str,
        workspace_id: str,
        app_id: str,
        sidecar_id: str,
        sidecar_instance_id: str,
    ) -> str | None:
        """Return pending/ready only when the caller matches the full launch binding."""
        now = self._clock()
        digest = _token_digest(value)
        with self._lock:
            self._prune(now)
            confirmation = self._confirmations.get(digest)
            if confirmation is None or not _confirmation_matches(
                confirmation.binding,
                actor_user_id=actor_user_id,
                workspace_id=workspace_id,
                app_id=app_id,
                sidecar_id=sidecar_id,
                sidecar_instance_id=sidecar_instance_id,
            ):
                return None
            return "ready" if confirmation.confirmed else "pending"

    def validate_and_touch(
        self,
        value: str,
        *,
        host: str,
        rotate: bool = True,
    ) -> ValidatedSidecarBrowserSession | None:
        now = self._clock()
        presented_digest = _token_digest(value)
        with self._lock:
            self._prune(now)
            digest = self._resolve_alias(presented_digest, now=now)
            session = self._sessions.get(digest)
            if session is None or not secrets.compare_digest(session.binding.host, host):
                return None
            idle_expires_at = min(now + SESSION_IDLE_TTL_SECONDS, session.absolute_expires_at)
            touched = replace(session, last_seen_at=now, idle_expires_at=idle_expires_at)
            rotated_value: str | None = None
            if rotate and now - session.rotated_at >= SESSION_ROTATION_SECONDS:
                rotated_value = secrets.token_urlsafe(32)
                rotated_digest = _token_digest(rotated_value)
                touched = replace(touched, token_digest=rotated_digest, rotated_at=now)
                self._sessions.pop(digest, None)
                self._sessions[rotated_digest] = touched
                confirmation_digest = self._session_confirmations.pop(digest, None)
                if confirmation_digest is not None:
                    self._session_confirmations[rotated_digest] = confirmation_digest
                self._aliases[presented_digest] = (rotated_digest, now + SESSION_ROTATION_GRACE_SECONDS)
            else:
                self._sessions[digest] = touched
            return ValidatedSidecarBrowserSession(session=touched, rotated_value=rotated_value)

    def validate(self, value: str, *, host: str) -> SidecarBrowserSession | None:
        """Validate a session without extending or rotating it."""
        now = self._clock()
        presented_digest = _token_digest(value)
        with self._lock:
            self._prune(now)
            digest = self._resolve_alias(presented_digest, now=now)
            session = self._sessions.get(digest)
            if session is None or not secrets.compare_digest(session.binding.host, host):
                return None
            return session

    def revoke_actor(self, actor_user_id: str) -> None:
        self._revoke(lambda binding: binding.actor_user_id == actor_user_id)

    def revoke_app(self, *, workspace_id: str, app_id: str) -> None:
        self._revoke(lambda binding: binding.workspace_id == workspace_id and binding.app_id == app_id)

    def revoke_sidecar(self, *, workspace_id: str, app_id: str, sidecar_id: str) -> None:
        self._revoke(
            lambda binding: binding.workspace_id == workspace_id
            and binding.app_id == app_id
            and binding.sidecar_id == sidecar_id
        )

    def revoke_all(self) -> None:
        with self._lock:
            self._tickets.clear()
            self._confirmations.clear()
            self._sessions.clear()
            self._session_confirmations.clear()
            self._aliases.clear()

    def _revoke(self, predicate: Callable[[SidecarBrowserBinding], bool]) -> None:
        with self._lock:
            self._tickets = {
                digest: ticket for digest, ticket in self._tickets.items() if not predicate(ticket.binding)
            }
            self._confirmations = {
                digest: confirmation
                for digest, confirmation in self._confirmations.items()
                if not predicate(confirmation.binding)
            }
            removed_digests = {
                digest for digest, session in self._sessions.items() if predicate(session.binding)
            }
            self._sessions = {
                digest: session for digest, session in self._sessions.items() if digest not in removed_digests
            }
            self._session_confirmations = {
                digest: confirmation_digest
                for digest, confirmation_digest in self._session_confirmations.items()
                if digest not in removed_digests and confirmation_digest in self._confirmations
            }
            self._aliases = {
                alias: target
                for alias, target in self._aliases.items()
                if target[0] not in removed_digests
            }

    def _resolve_alias(self, digest: str, *, now: float) -> str:
        target = self._aliases.get(digest)
        if target is None:
            return digest
        target_digest, expires_at = target
        if expires_at < now:
            self._aliases.pop(digest, None)
            return digest
        return target_digest

    def _prune(self, now: float) -> None:
        self._tickets = {
            digest: ticket for digest, ticket in self._tickets.items() if ticket.expires_at >= now
        }
        self._confirmations = {
            digest: confirmation
            for digest, confirmation in self._confirmations.items()
            if confirmation.expires_at >= now
        }
        expired_sessions = {
            digest
            for digest, session in self._sessions.items()
            if session.idle_expires_at < now or session.absolute_expires_at < now
        }
        for digest in expired_sessions:
            self._sessions.pop(digest, None)
            confirmation_digest = self._session_confirmations.pop(digest, None)
            if confirmation_digest is not None:
                self._confirmations.pop(confirmation_digest, None)
        self._session_confirmations = {
            digest: confirmation_digest
            for digest, confirmation_digest in self._session_confirmations.items()
            if digest in self._sessions and confirmation_digest in self._confirmations
        }
        self._aliases = {
            alias: target
            for alias, target in self._aliases.items()
            if target[1] >= now and target[0] not in expired_sessions
        }


def _token_digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _confirmation_matches(
    binding: SidecarBrowserBinding,
    *,
    actor_user_id: str,
    workspace_id: str,
    app_id: str,
    sidecar_id: str,
    sidecar_instance_id: str,
) -> bool:
    return all(
        secrets.compare_digest(actual, expected)
        for actual, expected in (
            (binding.actor_user_id, actor_user_id),
            (binding.workspace_id, workspace_id),
            (binding.app_id, app_id),
            (binding.sidecar_id, sidecar_id),
            (binding.sidecar_instance_id, sidecar_instance_id),
        )
    )
