"""Parent-bound isolated launch contract for widgets nested inside app frames."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.api.app_frame_launch import (
    APP_FRAME_BOOTSTRAP_PATH,
    APP_FRAME_SIDECAR_ID,
    APP_FRAME_SURFACE_KIND,
    app_frame_label,
    app_generation_id,
    content_security_policy,
    ensure_app_frame_tls,
    isolated_origin,
    normalize_origin,
    request_platform_origin,
)
from core.api.app_frame_scope import (
    APP_FRAME_APP_ID_SCOPE_KEY,
    APP_FRAME_ORIGIN_SCOPE_KEY,
    APP_FRAME_PROXY_SCOPE_KEY,
)
from core.api.http import StartResponse, json_response, read_json_body
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession
from core.api.widget_browser_launch_policy import (
    bounded_request_string,
    clean_nested_widget_launch_path,
    nested_widget_context_matches,
    verify_nested_widget_context,
)
from core.apps.errors import AppHostingError
from core.apps.sidecar_browser_sessions import MAX_TICKET_TTL_SECONDS, SidecarBrowserBinding
from core.apps.widgets import resolve_workspace_widget
from core.observability.service import record_platform_audit, record_platform_event
from core.shared.browser_origin_tls import BrowserOriginTlsError


WIDGET_BROWSER_LAUNCH_PATH = "/api/apps/widgets/browser-launch"
_REQUEST_FIELDS = {"context_token", "frontend_path", "owner_app_id", "widget_id"}
_MAX_OPAQUE_TOKEN_LENGTH = 16_384


def handle_widget_browser_launch(
    state: PlatformState,
    context: RequestSession | None,
    environ: dict[str, Any],
    start_response: StartResponse,
    *,
    start_path: Path,
) -> list[bytes] | None:
    """Issue a widget-owner ticket only to an authenticated isolated parent."""
    if str(environ.get("PATH_INFO") or "/") != WIDGET_BROWSER_LAUNCH_PATH:
        return None
    if str(environ.get("REQUEST_METHOD") or "GET").upper() != "POST":
        return _error(start_response, "method_not_allowed", "405 Method Not Allowed")
    if context is None:
        return _error(start_response, "authentication_required", "401 Unauthorized")

    parent_origin = str(environ.get(APP_FRAME_ORIGIN_SCOPE_KEY) or "").strip()
    parent_app_id = str(environ.get(APP_FRAME_APP_ID_SCOPE_KEY) or "").strip()
    if environ.get(APP_FRAME_PROXY_SCOPE_KEY) is not True or not parent_app_id or not parent_origin:
        return _denied(
            state,
            context=context,
            start_response=start_response,
            error="nested_widget_parent_required",
            detail="Nested widget launch requires an authenticated isolated parent frame.",
            parent_app_id=parent_app_id,
        )

    try:
        platform_origin = request_platform_origin(environ)
        if normalize_origin(parent_origin) != parent_origin or parent_origin == platform_origin:
            raise AppHostingError("Nested widget parent origin is invalid.")
    except AppHostingError:
        return _denied(
            state,
            context=context,
            start_response=start_response,
            error="nested_widget_parent_invalid",
            detail="Nested widget launch received an invalid parent binding.",
            parent_app_id=parent_app_id,
        )

    body = read_json_body(environ)
    if set(body) != _REQUEST_FIELDS:
        return _error(start_response, "invalid_widget_browser_launch_request", "400 Bad Request")
    owner_app_id = bounded_request_string(body.get("owner_app_id"), maximum=256)
    widget_id = bounded_request_string(body.get("widget_id"), maximum=256)
    context_token = bounded_request_string(body.get("context_token"), maximum=_MAX_OPAQUE_TOKEN_LENGTH)
    frontend_path = bounded_request_string(body.get("frontend_path"), maximum=4096)
    if not all((owner_app_id, widget_id, context_token, frontend_path)):
        return _error(start_response, "invalid_widget_browser_launch_request", "400 Bad Request")

    resolved = resolve_workspace_widget(
        state.app_store,
        workspace_id=context.workspace_id,
        owner_app_id=owner_app_id,
        widget_id=widget_id,
        workspace_store=state.workspace_store,
        user=context.user,
        start_path=start_path,
    )
    if resolved is None:
        return _denied(
            state,
            context=context,
            start_response=start_response,
            error="widget_not_available",
            detail="Nested widget owner or declaration is unavailable.",
            owner_app_id=owner_app_id,
            parent_app_id=parent_app_id,
            widget_id=widget_id,
        )

    widget_context = verify_nested_widget_context(context_token)
    if not nested_widget_context_matches(
        widget_context,
        context=context,
        owner_app_id=owner_app_id,
        widget_id=widget_id,
        widget_host=resolved.widget.host,
        content_kinds=resolved.widget.content_kinds,
    ):
        return _denied(
            state,
            context=context,
            start_response=start_response,
            error="widget_context_mismatch",
            detail="Nested widget launch context does not match its declared surface.",
            owner_app_id=owner_app_id,
            parent_app_id=parent_app_id,
            widget_id=widget_id,
        )

    try:
        clean_path = clean_nested_widget_launch_path(
            frontend_path,
            owner_app_id=owner_app_id,
            widget_id=widget_id,
            context_token=context_token,
        )
        generation_id = app_generation_id(resolved.binding)
        origin, host, secure = isolated_origin(
            environ,
            label=app_frame_label(
                actor_user_id=context.user.user_id,
                workspace_id=context.workspace_id,
                app_id=resolved.binding.app_id,
                generation_id=generation_id,
                platform_session_id=context.session.session_id,
                parent_origin=parent_origin,
            ),
            platform_origin=platform_origin,
        )
        ensure_app_frame_tls(
            state,
            context=context,
            environ=environ,
            start_path=start_path,
            platform_origin=platform_origin,
            requested_host=host,
        )
    except AppHostingError as error:
        return _denied(
            state,
            context=context,
            start_response=start_response,
            error="widget_frame_unavailable",
            detail=str(error),
            owner_app_id=owner_app_id,
            parent_app_id=parent_app_id,
            widget_id=widget_id,
            status="404 Not Found",
        )
    except BrowserOriginTlsError:
        return _error(start_response, "app_frame_tls_unavailable", "503 Service Unavailable")

    binding = SidecarBrowserBinding(
        actor_user_id=context.user.user_id,
        workspace_id=context.workspace_id,
        app_id=resolved.binding.app_id,
        sidecar_id=APP_FRAME_SIDECAR_ID,
        host=host,
        origin=origin,
        platform_origin=platform_origin,
        generation_id=generation_id,
        sidecar_instance_id=context.session.session_id,
        clean_path=clean_path,
        secure=secure,
        content_security_policy=content_security_policy(
            platform_origin,
            parent_origin=parent_origin,
        ),
        surface_kind=APP_FRAME_SURFACE_KIND,
        platform_session_id=context.session.session_id,
        mount_app_id=resolved.binding.mount_app_id or resolved.binding.app_id,
        parent_origin=parent_origin,
        parent_app_id=parent_app_id,
        widget_host=resolved.widget.host,
        widget_id=widget_id,
    )
    ticket = state.sidecar_browser_sessions.issue_ticket(binding)
    record_platform_event(
        state.observability_store,
        event_type="apps.widgets.browser_launch",
        event_plane="app",
        source_domain="apps.widgets",
        workspace_id=context.workspace_id,
        app_id=owner_app_id,
        payload={
            "host_app_id": resolved.widget.host,
            "owner_app_id": owner_app_id,
            "parent_app_id": parent_app_id,
            "widget_id": widget_id,
        },
    )
    return json_response(
        start_response,
        {
            "bootstrap_url": f"{origin}{APP_FRAME_BOOTSTRAP_PATH}",
            "bootstrap_transport": "cors",
            "expires_in_seconds": MAX_TICKET_TTL_SECONDS,
            "frontend_url": f"{origin}{clean_path}",
            "host_app_id": resolved.widget.host,
            "method": "POST",
            "origin": origin,
            "owner_app_id": owner_app_id,
            "parent_origin": parent_origin,
            "ticket": ticket.value,
            "ticket_field": "ticket",
            "widget_id": widget_id,
        },
        headers=_launch_headers(),
    )


def _denied(
    state: PlatformState,
    *,
    context: RequestSession,
    start_response: StartResponse,
    error: str,
    detail: str,
    owner_app_id: str = "",
    parent_app_id: str = "",
    widget_id: str = "",
    status: str = "403 Forbidden",
) -> list[bytes]:
    record_platform_audit(
        state.observability_store,
        action="apps.widgets.browser_launch",
        status="denied",
        source_domain="apps.widgets",
        detail=detail,
        workspace_id=context.workspace_id,
        app_id=owner_app_id or None,
        payload={
            "owner_app_id": owner_app_id,
            "parent_app_id": parent_app_id,
            "reason": error,
            "widget_id": widget_id,
        },
    )
    return _error(start_response, error, status)


def _error(start_response: StartResponse, error: str, status: str) -> list[bytes]:
    return json_response(
        start_response,
        {"error": error},
        status=status,
        headers=_launch_headers(),
    )


def _launch_headers() -> list[tuple[str, str]]:
    return [("Cache-Control", "no-store"), ("Referrer-Policy", "no-referrer")]
