"""Memory-only, action-scoped app access for a user-authorized Chrome extension."""

from dataclasses import dataclass, replace
from hashlib import sha256
import re
import secrets
from threading import Lock
import time

from core.apps.sidecar_browser_sessions import SidecarBrowserBinding


IDLE_SECONDS = 10 * 60
ABSOLUTE_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class AppBackgroundGrant:
    binding: SidecarBrowserBinding
    client_origin: str
    actions: frozenset[str]
    idle_expires_at: float
    absolute_expires_at: float


class AppBackgroundGrantStore:
    """No platform cookies or broad user tokens are delivered to the client."""

    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._lock = Lock()
        self._grants: dict[str, AppBackgroundGrant] = {}

    def issue(self, binding, client_origin, actions):
        if not isinstance(client_origin, str) or not re.fullmatch(r"chrome-extension://[a-p]{32}", client_origin):
            raise ValueError("invalid_background_client")
        if not isinstance(actions, list) or not 1 <= len(actions) <= 32 or any(
            not isinstance(action, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,99}", action) for action in actions
        ) or len(set(actions)) != len(actions):
            raise ValueError("invalid_background_actions")
        now = self._clock()
        value = secrets.token_urlsafe(32)
        with self._lock:
            self._prune(now)
            owned = [grant for grant in self._grants.values() if (
                grant.binding.actor_user_id, grant.binding.workspace_id, grant.binding.app_id, grant.binding.platform_session_id
            ) == (binding.actor_user_id, binding.workspace_id, binding.app_id, binding.platform_session_id)]
            if len(owned) >= 16 or len(self._grants) >= 4096:
                raise ValueError("background_grant_limit")
            self._grants[sha256(value.encode()).hexdigest()] = AppBackgroundGrant(
                binding, client_origin, frozenset(actions), now + IDLE_SECONDS, now + ABSOLUTE_SECONDS,
            )
        return value

    def validate(self, value, *, host, client_origin):
        if not isinstance(value, str) or not 20 <= len(value) <= 256:
            return None
        now = self._clock()
        with self._lock:
            self._prune(now)
            grant = self._grants.get(sha256(value.encode()).hexdigest())
            if grant is None or grant.binding.host != host or grant.client_origin != client_origin:
                return None
            return grant

    def touch(self, value):
        with self._lock:
            digest = sha256(value.encode()).hexdigest()
            grant = self._grants.get(digest)
            if grant:
                self._grants[digest] = replace(grant, idle_expires_at=min(self._clock() + IDLE_SECONDS, grant.absolute_expires_at))

    def revoke(self, value):
        with self._lock:
            self._grants.pop(sha256(value.encode()).hexdigest(), None)

    def _prune(self, now):
        for digest, grant in tuple(self._grants.items()):
            if min(grant.idle_expires_at, grant.absolute_expires_at) <= now:
                self._grants.pop(digest)
