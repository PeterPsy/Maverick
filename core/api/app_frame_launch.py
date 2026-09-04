"""Shared launch policy for isolated Maverick app and widget frames."""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any
from urllib.parse import urlsplit

from core.api.app_registry import enabled_app_items, resolve_app_surface, user_can_mount_app
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession
from core.apps.errors import AppHostingError, WorkspaceAppBindingNotFoundError
from core.apps.presentation import app_frontend_is_launchable
from core.identity.errors import UserNotFoundError
from core.shared.browser_origin_tls import (
    BrowserOriginTlsError,
    ensure_browser_origin_tls,
    managed_browser_origin_tls_enabled,
)


_DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)

APP_FRAME_BOOTSTRAP_PATH = "/.well-known/maverick-app-frame-bootstrap"
APP_FRAME_SIDECAR_ID = "__maverick_app_frame__"
APP_FRAME_SURFACE_KIND = "app-frame"


def authorized_app_surface(
    state: PlatformState,
    *,
    actor_user_id: str,
    workspace_id: str,
    app_id: str,
    start_path: Path,
) -> tuple[Any, Path, Any]:
    """Resolve one visible, launchable full-app surface."""
    if not app_id:
        raise AppHostingError("An app id is required for isolated frame launch.")
    user = state.identity_store.get_user(actor_user_id)
    binding, source_root, parsed = resolve_app_surface(
        state,
        workspace_id=workspace_id,
        app_id=app_id,
        start_path=start_path,
    )
    if not user_can_mount_app(
        state,
        user=user,
        workspace_id=workspace_id,
        visibility=parsed.contract.visibility,
    ):
        raise AppHostingError("The app frame is not visible to this actor.")
    if not app_frontend_is_launchable(parsed.contract) or parsed.contract.entrypoints.frontend is None:
        raise AppHostingError("The app does not expose a launchable frontend.")
    return binding, source_root, parsed


def app_generation_id(binding: Any) -> str:
    """Return the installation generation bound into browser authority."""
    identity = "\0".join(
        str(getattr(binding, field, "") or "")
        for field in ("binding_id", "source_record_id", "active_version", "data_root", "mount_app_id")
    )
    return sha256(identity.encode("utf-8")).hexdigest()


def app_frame_label(
    *,
    actor_user_id: str,
    workspace_id: str,
    app_id: str,
    generation_id: str,
    platform_session_id: str,
    parent_origin: str = "",
) -> str:
    """Derive an opaque host label, narrowing nested frames to their parent."""
    fields = [actor_user_id, workspace_id, app_id, generation_id, platform_session_id]
    if parent_origin:
        fields.append(parent_origin)
    identity = "\0".join(fields).encode("utf-8")
    return f"af-{sha256(identity).hexdigest()[:24]}"


def ensure_app_frame_tls(
    state: PlatformState,
    *,
    context: RequestSession,
    environ: dict[str, Any],
    start_path: Path,
    platform_origin: str,
    requested_host: str,
) -> None:
    """Ensure the requested exact frame host is covered by managed TLS."""
    if not managed_browser_origin_tls_enabled():
        return
    if os.environ.get("MAVERICK_SIDECAR_ORIGIN_MODE", "local").strip().lower() != "hosted":
        raise BrowserOriginTlsError("Managed browser-origin TLS requires hosted origins.")
    hosts = {requested_host}
    for item in enabled_app_items(
        state,
        workspace_id=context.workspace_id,
        start_path=start_path,
        user=context.user,
    ):
        if item.get("frontend_launchable") is not True:
            continue
        app_id = str(item.get("app_id") or "")
        try:
            binding, _source_root, _parsed = authorized_app_surface(
                state,
                actor_user_id=context.user.user_id,
                workspace_id=context.workspace_id,
                app_id=app_id,
                start_path=start_path,
            )
            _origin, candidate_host, _secure = isolated_origin(
                environ,
                label=app_frame_label(
                    actor_user_id=context.user.user_id,
                    workspace_id=context.workspace_id,
                    app_id=binding.app_id,
                    generation_id=app_generation_id(binding),
                    platform_session_id=context.session.session_id,
                ),
                platform_origin=platform_origin,
            )
        except (AppHostingError, UserNotFoundError, WorkspaceAppBindingNotFoundError):
            continue
        hosts.add(candidate_host)
    ensure_browser_origin_tls(
        sorted(hosts),
        group_key=f"app-frame-session:{context.session.session_id}",
        repository_root=state.repository_root,
    )


def clean_app_launch_path(value: object, *, local_app_id: str, mount_app_id: str) -> str:
    """Validate one full-app or same-owner widget launch path."""
    raw = clean_relative_origin_url(value)
    path = urlsplit(raw).path
    app_prefix = f"/apps/{mount_app_id}/"
    widget_prefixes = {
        f"/api/apps/widgets/{local_app_id}/",
        f"/api/apps/widgets/{mount_app_id}/",
    }
    if not path.startswith(app_prefix) and not any(path.startswith(prefix) for prefix in widget_prefixes):
        raise AppHostingError("App frame launch path does not belong to the requested app.")
    return raw


def clean_relative_origin_url(value: object) -> str:
    """Require one canonical relative-origin URL without traversal."""
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    path = parsed.path
    if (
        not path.startswith("/")
        or path.startswith("//")
        or parsed.scheme
        or parsed.netloc
        or "\\" in raw
        or any(ord(character) < 32 for character in raw)
        or any(part in {".", ".."} for part in PurePosixPath(path).parts)
    ):
        raise AppHostingError("App frame launch path must be one clean relative-origin URL.")
    return raw


def request_platform_origin(environ: dict[str, Any]) -> str:
    """Resolve the exact public platform origin from a launch request."""
    scheme = str(environ.get("wsgi.url_scheme") or "").strip().lower()
    host = str(environ.get("HTTP_HOST") or "").strip().lower()
    if scheme not in {"http", "https"} or not valid_exact_host(host):
        raise AppHostingError("The platform request does not provide one exact HTTP Host and scheme.")
    return normalize_origin(f"{scheme}://{host}")


def isolated_origin(
    environ: dict[str, Any],
    *,
    label: str,
    platform_origin: str,
) -> tuple[str, str, bool]:
    """Resolve the isolated origin for local or hosted deployment mode."""
    mode = os.environ.get("MAVERICK_SIDECAR_ORIGIN_MODE", "local").strip().lower() or "local"
    platform = urlsplit(platform_origin)
    if mode == "local":
        hostname = str(platform.hostname or "").lower()
        if not hostname.endswith(".localhost"):
            raise AppHostingError("Local app-frame origins require a named .localhost platform host.")
        suffix = f":{platform.port}" if platform.port is not None else ""
        host = f"{label}.sidecars.{hostname}{suffix}"
        return f"{platform.scheme}://{host}", host, platform.scheme == "https"
    if mode == "hosted":
        domain = os.environ.get("MAVERICK_SIDECAR_INSTALLATION_DOMAIN", "").strip().lower().rstrip(".")
        configured = os.environ.get("MAVERICK_SIDECAR_PLATFORM_ORIGIN", "").strip()
        if not domain or not _DOMAIN_PATTERN.fullmatch(domain) or not configured:
            raise AppHostingError("Hosted app-frame origins require the sidecar installation domain and platform origin.")
        configured_origin = normalize_origin(configured)
        if configured_origin != platform_origin or not platform_origin.startswith("https://"):
            raise AppHostingError("Hosted app-frame origins require the exact configured HTTPS platform origin.")
        host = f"{label}.sidecars.{domain}"
        return f"https://{host}", host, True
    raise AppHostingError("MAVERICK_SIDECAR_ORIGIN_MODE must be `local` or `hosted`.")


def normalize_origin(value: str) -> str:
    """Return one exact normalized HTTP(S) origin."""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise AppHostingError("App-frame platform origin configuration is invalid.")
    if parsed.username is not None or parsed.password is not None:
        raise AppHostingError("App-frame platform origin configuration is invalid.")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def content_security_policy(platform_origin: str, *, parent_origin: str = "") -> str:
    """Allow only the exact authenticated embedding ancestry."""
    ancestors = ["'self'", platform_origin]
    if parent_origin and parent_origin not in ancestors:
        ancestors.append(parent_origin)
    return "; ".join(
        (
            "base-uri 'self'",
            "object-src 'none'",
            f"frame-ancestors {' '.join(ancestors)}",
        )
    )


def valid_exact_host(value: str) -> bool:
    """Reject ambiguous or malformed HTTP Host values."""
    if not value or any(character.isspace() for character in value) or "," in value or "/" in value or "@" in value:
        return False
    try:
        parsed = urlsplit(f"//{value}")
        _ = parsed.port
    except ValueError:
        return False
    return bool(parsed.hostname)
