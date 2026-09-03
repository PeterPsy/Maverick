"""Host-routed, per-app browser origins for untrusted frontend frames."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, urlsplit

from core.api.app_frame_assets import rewrite_public_app_asset_urls
from core.api.app_frame_scope import (
    APP_FRAME_OWNER_MISMATCH_ERROR,
    app_frame_path_matches_owner,
    bind_app_frame_scope,
)
from core.api.app_registry import enabled_app_items, resolve_app_surface, user_can_mount_app
from core.api.http import StartResponse, json_response, read_json_body
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession, SESSION_COOKIE
from core.apps.errors import AppHostingError, WorkspaceAppBindingNotFoundError
from core.apps.presentation import app_frontend_is_launchable
from core.apps.sidecar_browser_sessions import (
    MAX_TICKET_TTL_SECONDS,
    SESSION_IDLE_TTL_SECONDS,
    SidecarBrowserBinding,
    SidecarBrowserSession,
)
from core.identity.errors import SessionNotFoundError, UserNotFoundError
from core.shared.browser_origin_tls import (
    BrowserOriginTlsError,
    ensure_browser_origin_tls,
    managed_browser_origin_tls_enabled,
)
from core.workspaces.service import resolve_active_workspace_for_user


AsgiReceive = Callable[[], Awaitable[dict[str, Any]]]
AsgiSend = Callable[[dict[str, Any]], Awaitable[None]]
AsgiForward = Callable[[dict[str, Any], AsgiReceive, AsgiSend], Awaitable[None]]

APP_FRAME_LAUNCH_PATH = "/api/app-frames/browser-launch"
APP_FRAME_BOOTSTRAP_PATH = "/.well-known/maverick-app-frame-bootstrap"
APP_FRAME_COOKIE_NAME = "maverick_app_frame_session"
APP_FRAME_SURFACE_KIND = "app-frame"
APP_FRAME_SIDECAR_ID = "__maverick_app_frame__"
_MAX_BOOTSTRAP_BODY_BYTES = 4096
_DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def handle_app_frame_browser_launch(
    state: PlatformState,
    context: RequestSession | None,
    environ: dict[str, Any],
    start_response: StartResponse,
    *,
    start_path: Path,
) -> list[bytes] | None:
    """Issue a one-shot POST bootstrap for one authorized app frontend."""
    if str(environ.get("PATH_INFO") or "/") != APP_FRAME_LAUNCH_PATH:
        return None
    if str(environ.get("REQUEST_METHOD") or "GET").upper() != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    if context is None:
        return json_response(start_response, {"error": "authentication_required"}, status="401 Unauthorized")
    body = read_json_body(environ)
    if set(body) != {"app_id", "path"}:
        return json_response(start_response, {"error": "invalid_app_frame_launch_request"}, status="400 Bad Request")
    app_id = str(body.get("app_id") or "").strip()
    try:
        binding, _source_root, parsed = _authorized_app_surface(
            state,
            actor_user_id=context.user.user_id,
            workspace_id=context.workspace_id,
            app_id=app_id,
            start_path=start_path,
        )
        clean_path = _clean_app_launch_path(
            body.get("path"),
            local_app_id=binding.app_id,
            mount_app_id=binding.mount_app_id or binding.app_id,
        )
        platform_origin = _request_platform_origin(environ)
        origin, host, secure = _isolated_origin(
            environ,
            label=_app_frame_label(
                actor_user_id=context.user.user_id,
                workspace_id=context.workspace_id,
                app_id=binding.app_id,
                generation_id=_app_generation_id(binding),
                platform_session_id=context.session.session_id,
            ),
            platform_origin=platform_origin,
        )
    except (AppHostingError, UserNotFoundError, WorkspaceAppBindingNotFoundError) as error:
        return json_response(
            start_response,
            {"error": "app_frame_unavailable", "detail": str(error)},
            status="404 Not Found",
            headers=_launch_headers(),
        )
    try:
        _ensure_app_frame_tls(
            state,
            context=context,
            environ=environ,
            start_path=start_path,
            platform_origin=platform_origin,
            requested_host=host,
        )
    except BrowserOriginTlsError:
        return json_response(
            start_response,
            {"error": "app_frame_tls_unavailable"},
            status="503 Service Unavailable",
            headers=_launch_headers(),
        )
    generation_id = _app_generation_id(binding)
    browser_binding = SidecarBrowserBinding(
        actor_user_id=context.user.user_id,
        workspace_id=context.workspace_id,
        app_id=binding.app_id,
        sidecar_id=APP_FRAME_SIDECAR_ID,
        host=host,
        origin=origin,
        platform_origin=platform_origin,
        generation_id=generation_id,
        sidecar_instance_id=context.session.session_id,
        clean_path=clean_path,
        secure=secure,
        content_security_policy=_content_security_policy(platform_origin),
        surface_kind=APP_FRAME_SURFACE_KIND,
        platform_session_id=context.session.session_id,
        mount_app_id=binding.mount_app_id or binding.app_id,
    )
    ticket = state.sidecar_browser_sessions.issue_ticket(browser_binding)
    return json_response(
        start_response,
        {
            "origin": origin,
            "bootstrap_url": f"{origin}{APP_FRAME_BOOTSTRAP_PATH}",
            "method": "POST",
            "ticket_field": "ticket",
            "ticket": ticket.value,
            "expires_in_seconds": MAX_TICKET_TTL_SECONDS,
        },
        headers=_launch_headers(),
    )


def handle_app_frame_oauth_relay(
    state: PlatformState,
    context: RequestSession | None,
    environ: dict[str, Any],
    start_response: StartResponse,
    *,
    start_path: Path,
) -> list[bytes] | None:
    """Relay registered platform OAuth callbacks into the app's isolated origin."""
    # The isolated proxy must serve the app SPA callback itself. Relaying that
    # second hop would recursively mint new frame origins forever.
    if environ.get("maverick.app_frame_proxy") is True:
        return None
    path = str(environ.get("PATH_INFO") or "/")
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    match = re.fullmatch(r"/apps/([^/]+)/oauth/callback/?", path)
    if match is None or method not in {"GET", "HEAD"}:
        return None
    if context is None:
        return json_response(start_response, {"error": "authentication_required"}, status="401 Unauthorized")
    app_id = match.group(1)
    try:
        binding, _source_root, _parsed = _authorized_app_surface(
            state,
            actor_user_id=context.user.user_id,
            workspace_id=context.workspace_id,
            app_id=app_id,
            start_path=start_path,
        )
    except (AppHostingError, WorkspaceAppBindingNotFoundError):
        return json_response(start_response, {"error": "app_frame_unavailable"}, status="404 Not Found")
    public_app_id = binding.mount_app_id or binding.app_id
    script = (
        "(()=>{const app=" + json.dumps(public_app_id) + ";"
        "const target=location.pathname+location.search+location.hash;"
        "fetch('/api/app-frames/browser-launch',{method:'POST',credentials:'same-origin',"
        "headers:{'Content-Type':'application/json'},body:JSON.stringify({app_id:app,path:target})})"
        ".then(r=>r.ok?r.json():Promise.reject(new Error('launch failed'))).then(l=>{"
        "const f=document.createElement('form');f.method='POST';f.action=l.bootstrap_url;"
        "const i=document.createElement('input');i.type='hidden';i.name=l.ticket_field;i.value=l.ticket;"
        "f.append(i);document.body.append(f);f.submit();}).catch(()=>{"
        "document.body.textContent='Unable to open the isolated app callback.';});})();"
    )
    body = (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Completing authorization</title></head>"
        "<body><p>Completing authorization…</p><script>" + script + "</script></body></html>"
    ).encode("utf-8")
    headers = [
        ("Content-Type", "text/html; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
        ("Referrer-Policy", "no-referrer"),
        (
            "Content-Security-Policy",
            "default-src 'none'; script-src 'unsafe-inline'; connect-src 'self'; "
            "form-action http: https:; frame-ancestors 'none'; base-uri 'none'",
        ),
        ("X-Content-Type-Options", "nosniff"),
    ]
    start_response("200 OK", headers)
    return [] if method == "HEAD" else [body]


def is_reserved_app_frame_browser_host(scope: dict[str, Any]) -> bool:
    """Return whether a request targets the reserved app-frame host namespace."""
    values = _header_values(scope, b"host")
    return any(_looks_like_app_frame_host(value) for value in values)


async def handle_app_frame_browser_origin(
    state: PlatformState,
    *,
    scope: dict[str, Any],
    receive: AsgiReceive,
    send: AsgiSend,
    start_path: Path,
    forward: AsgiForward,
) -> None:
    """Authenticate an isolated origin request and proxy it into PlatformHost."""
    hosts = _header_values(scope, b"host")
    if len(hosts) != 1 or not _valid_exact_host(hosts[0]):
        await _send_json(send, {"error": "app_frame_host_invalid"}, status=421, headers=_denial_headers())
        return
    host = hosts[0].lower()
    path = str(scope.get("path") or "/")
    method = str(scope.get("method") or "GET").upper()
    if path == APP_FRAME_BOOTSTRAP_PATH:
        await _handle_bootstrap(
            state,
            scope=scope,
            receive=receive,
            send=send,
            host=host,
            method=method,
            start_path=start_path,
        )
        return

    resolved = await _validated_request_session(state, scope=scope, send=send, host=host, start_path=start_path)
    if resolved is None:
        return
    token, session = resolved
    if not _request_path_matches_session(scope, session):
        await _deny(send, session.binding, APP_FRAME_OWNER_MISMATCH_ERROR, status=403)
        return
    if method not in _SAFE_METHODS:
        if _header_values(scope, b"origin") != [session.binding.origin] \
                or _header_values(scope, b"sec-fetch-site") != ["same-origin"]:
            await _deny(send, session.binding, "csrf_proof_required", status=403)
            return
    validated = state.sidecar_browser_sessions.validate_and_touch(token, host=host)
    if validated is None or validated.session.binding.surface_kind != APP_FRAME_SURFACE_KIND:
        await _deny(send, session.binding, "app_frame_session_expired")
        return

    transformed = _platform_scope(scope, validated.session, websocket=False)
    response = _IsolatedHttpResponse(
        send,
        binding=validated.session.binding,
        rotated_value=validated.rotated_value,
        request_method=method,
    )
    await forward(transformed, receive, response.send)
    await response.finish()


async def handle_app_frame_browser_websocket(
    state: PlatformState,
    *,
    scope: dict[str, Any],
    receive: AsgiReceive,
    send: AsgiSend,
    start_path: Path,
    forward: AsgiForward,
) -> None:
    """Authorize an isolated-origin WebSocket and bind it to the login session."""
    hosts = _header_values(scope, b"host")
    if len(hosts) != 1 or not _valid_exact_host(hosts[0]):
        await send({"type": "websocket.close", "code": 4401})
        return
    host = hosts[0].lower()
    resolved = _request_session(state, scope=scope, host=host, start_path=start_path)
    if resolved is None:
        await send({"type": "websocket.close", "code": 4401})
        return
    _token, session = resolved
    if _header_values(scope, b"origin") != [session.binding.origin]:
        await send({"type": "websocket.close", "code": 4403})
        return
    if not _request_path_matches_session(scope, session):
        await send({"type": "websocket.close", "code": 4403})
        return
    await forward(_platform_scope(scope, session, websocket=True), receive, send)


async def _validated_request_session(
    state: PlatformState,
    *,
    scope: dict[str, Any],
    send: AsgiSend,
    host: str,
    start_path: Path,
) -> tuple[str, SidecarBrowserSession] | None:
    cookies = _header_values(scope, b"cookie")
    if len(cookies) > 1:
        await _send_json(send, {"error": "ambiguous_cookie"}, status=401, headers=_denial_headers())
        return None
    token = _cookie_value(cookies[0] if cookies else "", APP_FRAME_COOKIE_NAME)
    session = state.sidecar_browser_sessions.validate(token, host=host) if token else None
    if session is None or session.binding.surface_kind != APP_FRAME_SURFACE_KIND:
        await _send_json(send, {"error": "app_frame_session_required"}, status=401, headers=_denial_headers())
        return None
    if _current_app_frame(state, session, start_path=start_path) is None:
        state.sidecar_browser_sessions.revoke_app(
            workspace_id=session.binding.workspace_id,
            app_id=session.binding.app_id,
        )
        await _deny(send, session.binding, "app_frame_authority_stale")
        return None
    return token, session


def _request_session(
    state: PlatformState,
    *,
    scope: dict[str, Any],
    host: str,
    start_path: Path,
) -> tuple[str, SidecarBrowserSession] | None:
    cookies = _header_values(scope, b"cookie")
    if len(cookies) > 1:
        return None
    token = _cookie_value(cookies[0] if cookies else "", APP_FRAME_COOKIE_NAME)
    session = state.sidecar_browser_sessions.validate(token, host=host) if token else None
    if session is None or session.binding.surface_kind != APP_FRAME_SURFACE_KIND:
        return None
    if _current_app_frame(state, session, start_path=start_path) is None:
        return None
    return token, session


async def _handle_bootstrap(
    state: PlatformState,
    *,
    scope: dict[str, Any],
    receive: AsgiReceive,
    send: AsgiSend,
    host: str,
    method: str,
    start_path: Path,
) -> None:
    if method != "POST":
        await _send_json(send, {"error": "method_not_allowed"}, status=405, headers=_denial_headers())
        return
    if bytes(scope.get("query_string") or b""):
        await _send_json(send, {"error": "bootstrap_url_must_be_clean"}, status=400, headers=_denial_headers())
        return
    content_types = _header_values(scope, b"content-type")
    if len(content_types) != 1 or content_types[0].split(";", 1)[0].strip().lower() != "application/x-www-form-urlencoded":
        await _send_json(send, {"error": "bootstrap_form_required"}, status=400, headers=_denial_headers())
        return
    body = await _read_bounded_body(receive, maximum=_MAX_BOOTSTRAP_BODY_BYTES)
    if body is None:
        await _send_json(send, {"error": "bootstrap_body_too_large"}, status=413, headers=_denial_headers())
        return
    try:
        fields = parse_qs(body.decode("utf-8"), keep_blank_values=True, strict_parsing=True)
    except (UnicodeDecodeError, ValueError):
        fields = {}
    ticket_values = fields.get("ticket", [])
    if set(fields) != {"ticket"} or len(ticket_values) != 1 or not ticket_values[0]:
        await _send_json(send, {"error": "bootstrap_ticket_invalid"}, status=400, headers=_denial_headers())
        return
    issued = state.sidecar_browser_sessions.consume_ticket(ticket_values[0], host=host)
    if issued is None or issued.session.binding.surface_kind != APP_FRAME_SURFACE_KIND:
        await _send_json(send, {"error": "bootstrap_ticket_expired_or_spent"}, status=410, headers=_denial_headers())
        return
    if _current_app_frame(state, issued.session, start_path=start_path) is None:
        await _deny(send, issued.session.binding, "app_frame_authority_stale", status=410)
        return
    if not state.sidecar_browser_sessions.confirm_bootstrap(issued.session):
        await _deny(send, issued.session.binding, "bootstrap_confirmation_unavailable", status=410)
        return
    binding = issued.session.binding
    headers = _security_headers(binding)
    headers.extend(
        [
            ("Location", binding.clean_path),
            ("Set-Cookie", _session_cookie(issued.value, secure=binding.secure)),
        ]
    )
    await send(
        {
            "type": "http.response.start",
            "status": 303,
            "headers": [(name.lower().encode("latin1"), value.encode("latin1")) for name, value in headers],
        }
    )
    await send({"type": "http.response.body", "body": b"", "more_body": False})


def _current_app_frame(
    state: PlatformState,
    session: SidecarBrowserSession,
    *,
    start_path: Path,
) -> tuple[Any, Path, Any] | None:
    binding = session.binding
    if not binding.platform_session_id or binding.platform_session_id != binding.sidecar_instance_id:
        return None
    try:
        auth_session = state.identity_store.get_auth_session(binding.platform_session_id)
        user = state.identity_store.get_user(binding.actor_user_id)
    except (SessionNotFoundError, UserNotFoundError):
        return None
    now = datetime.now(tz=UTC)
    if auth_session.user_id != user.user_id or auth_session.status != "active" or auth_session.expires_at <= now or not user.is_active:
        return None
    selection = resolve_active_workspace_for_user(state.workspace_store, user_id=user.user_id, now=now)
    if selection is None or selection.workspace_id != binding.workspace_id:
        return None
    try:
        current = _authorized_app_surface(
            state,
            actor_user_id=user.user_id,
            workspace_id=binding.workspace_id,
            app_id=binding.app_id,
            start_path=start_path,
        )
    except (AppHostingError, WorkspaceAppBindingNotFoundError):
        return None
    return current if _app_generation_id(current[0]) == binding.generation_id else None


def _authorized_app_surface(
    state: PlatformState,
    *,
    actor_user_id: str,
    workspace_id: str,
    app_id: str,
    start_path: Path,
) -> tuple[Any, Path, Any]:
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


def _platform_scope(scope: dict[str, Any], session: SidecarBrowserSession, *, websocket: bool) -> dict[str, Any]:
    binding = session.binding
    platform = urlsplit(binding.platform_origin)
    incoming_cookies = _header_values(scope, b"cookie")
    retained_cookies = _retained_app_cookies(incoming_cookies[0] if len(incoming_cookies) == 1 else "")
    cookie = f"{SESSION_COOKIE}={binding.platform_session_id}"
    if retained_cookies:
        cookie = f"{cookie}; {retained_cookies}"
    # Keep HTML bodies identity encoded so the response authority wrapper can
    # inject the exact-parent message relay without attempting to decode a
    # compressed representation. The browser may still negotiate compression
    # for immutable public assets through their direct platform URLs.
    removed = {
        b"accept-encoding",
        b"host",
        b"cookie",
        b"origin",
        b"referer",
        b"sec-fetch-site",
    }
    headers = [(name, value) for name, value in scope.get("headers", []) if name.lower() not in removed]
    headers.extend(
        [
            (b"host", platform.netloc.encode("latin1")),
            (b"cookie", cookie.encode("latin1")),
            (b"origin", binding.platform_origin.encode("latin1")),
            (b"referer", f"{binding.platform_origin}/".encode("latin1")),
            (b"sec-fetch-site", b"same-origin"),
        ]
    )
    port = platform.port or (443 if platform.scheme == "https" else 80)
    transformed = bind_app_frame_scope(
        scope,
        app_id=binding.app_id,
        mount_app_id=binding.mount_app_id or binding.app_id,
    )
    transformed.update(
        {
            "headers": headers,
            "scheme": (
                "wss"
                if websocket and platform.scheme == "https"
                else ("ws" if websocket else platform.scheme)
            ),
            "server": (str(platform.hostname or ""), port),
        }
    )
    return transformed


def _request_path_matches_session(scope: dict[str, Any], session: SidecarBrowserSession) -> bool:
    binding = session.binding
    return app_frame_path_matches_owner(
        str(scope.get("path") or "/"),
        app_id=binding.app_id,
        mount_app_id=binding.mount_app_id or binding.app_id,
    )


class _IsolatedHttpResponse:
    """Rewrite platform response authority and inject the shell-message relay."""

    def __init__(
        self,
        send: AsgiSend,
        *,
        binding: SidecarBrowserBinding,
        rotated_value: str | None,
        request_method: str,
    ) -> None:
        self._send = send
        self._binding = binding
        self._rotated_value = rotated_value
        self._request_method = request_method
        self._start: dict[str, Any] | None = None
        self._html = False
        self._body: list[bytes] = []
        self._finished = False

    async def send(self, message: dict[str, Any]) -> None:
        message_type = message.get("type")
        if message_type == "http.response.start":
            self._start = message
            self._html = _response_is_html(message)
            if not self._html:
                await self._send(self._rewritten_start(message))
            return
        if message_type != "http.response.body" or not self._html:
            await self._send(message)
            return
        self._body.append(bytes(message.get("body") or b""))
        if not message.get("more_body", False):
            await self._flush_html()

    async def finish(self) -> None:
        if self._finished:
            return
        if self._html:
            await self._flush_html()
            return
        if self._start is None:
            await _send_json(self._send, {"error": "app_frame_proxy_failed"}, status=502, headers=_denial_headers())
        self._finished = True

    async def _flush_html(self) -> None:
        if self._finished:
            return
        start = self._start or {"type": "http.response.start", "status": 502, "headers": []}
        body = b"" if self._request_method == "HEAD" else _inject_message_relay(
            b"".join(self._body),
            self._binding.platform_origin,
        )
        await self._send(self._rewritten_start(start, content_length=len(body)))
        await self._send({"type": "http.response.body", "body": body, "more_body": False})
        self._finished = True

    def _rewritten_start(self, message: dict[str, Any], *, content_length: int | None = None) -> dict[str, Any]:
        headers: list[tuple[bytes, bytes]] = []
        for name, value in message.get("headers", []):
            normalized = bytes(name).lower()
            if normalized in {
                b"cache-control",
                b"content-length",
                b"content-security-policy",
                b"cross-origin-resource-policy",
                b"referrer-policy",
                b"x-frame-options",
            }:
                continue
            if normalized == b"set-cookie" and _reserved_cookie(value):
                continue
            if normalized == b"location":
                value = _rewrite_platform_location(bytes(value), self._binding)
            headers.append((normalized, bytes(value)))
        headers.extend(
            (name.lower().encode("latin1"), value.encode("latin1"))
            for name, value in _security_headers(self._binding)
        )
        if self._rotated_value is not None:
            headers.append(
                (
                    b"set-cookie",
                    _session_cookie(self._rotated_value, secure=self._binding.secure).encode("latin1"),
                )
            )
            self._rotated_value = None
        if content_length is not None:
            headers.append((b"content-length", str(content_length).encode("ascii")))
        return {**message, "headers": headers}


def _inject_message_relay(body: bytes, platform_origin: str) -> bytes:
    try:
        html = body.decode("utf-8")
    except UnicodeDecodeError:
        return body
    html = rewrite_public_app_asset_urls(html, platform_origin)
    origin = json.dumps(platform_origin, ensure_ascii=True)
    script = (
        "<script>"
        "(()=>{const o=" + origin + ";"
        "const a=d=>{if(!d||d.type!=='maverick.shell.layout-changed'||typeof d.mobile!=='boolean')return;"
        "const r=document.documentElement,p=['--maverick-shell-mobile-status-bar-height',"
        "'--maverick-shell-mobile-header-height','--maverick-shell-mobile-content-top-offset'];"
        "if(d.mobile){r.setAttribute('data-maverick-shell-mobile-layout','true');"
        "r.style.setProperty(p[0],'env(safe-area-inset-top, 0px)');"
        "r.style.setProperty(p[1],'2.75rem');"
        "r.style.setProperty(p[2],'calc(env(safe-area-inset-top, 0px) + 2.75rem)');}"
        "else{r.removeAttribute('data-maverick-shell-mobile-layout');p.forEach(n=>r.style.removeProperty(n));}};"
        "Object.defineProperty(window,'__MAVERICK_PLATFORM_ORIGIN__',{value:o,configurable:false});"
        "a({type:'maverick.shell.layout-changed',mobile:new URLSearchParams(location.search).get('maverick_mobile_layout')==='1'});"
        "window.addEventListener('message',e=>{"
        "if(e.source!==window.parent||e.origin!==o)return;"
        "a(e.data);"
        "try{window.postMessage(e.data,window.location.origin,[...e.ports]);}"
        "catch(_){window.postMessage(e.data,window.location.origin);}},true);"
        "})();"
        "</script>"
    )
    match = re.search(r"<head(?:\s[^>]*)?>", html, flags=re.IGNORECASE)
    if match:
        html = f"{html[:match.end()]}{script}{html[match.end():]}"
    else:
        html = f"{script}{html}"
    return html.encode("utf-8")


def _app_generation_id(binding: Any) -> str:
    identity = "\0".join(
        str(getattr(binding, field, "") or "")
        for field in ("binding_id", "source_record_id", "active_version", "data_root", "mount_app_id")
    )
    return sha256(identity.encode("utf-8")).hexdigest()


def _app_frame_label(
    *,
    actor_user_id: str,
    workspace_id: str,
    app_id: str,
    generation_id: str,
    platform_session_id: str,
) -> str:
    identity = "\0".join(
        (actor_user_id, workspace_id, app_id, generation_id, platform_session_id)
    ).encode("utf-8")
    return f"af-{sha256(identity).hexdigest()[:24]}"


def _ensure_app_frame_tls(
    state: PlatformState,
    *,
    context: RequestSession,
    environ: dict[str, Any],
    start_path: Path,
    platform_origin: str,
    requested_host: str,
) -> None:
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
            binding, _source_root, _parsed = _authorized_app_surface(
                state,
                actor_user_id=context.user.user_id,
                workspace_id=context.workspace_id,
                app_id=app_id,
                start_path=start_path,
            )
            _origin, candidate_host, _secure = _isolated_origin(
                environ,
                label=_app_frame_label(
                    actor_user_id=context.user.user_id,
                    workspace_id=context.workspace_id,
                    app_id=binding.app_id,
                    generation_id=_app_generation_id(binding),
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


def _clean_app_launch_path(value: object, *, local_app_id: str, mount_app_id: str) -> str:
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
    app_prefix = f"/apps/{mount_app_id}/"
    widget_prefixes = {
        f"/api/apps/widgets/{local_app_id}/",
        f"/api/apps/widgets/{mount_app_id}/",
    }
    if not path.startswith(app_prefix) and not any(path.startswith(prefix) for prefix in widget_prefixes):
        raise AppHostingError("App frame launch path does not belong to the requested app.")
    return raw


def _request_platform_origin(environ: dict[str, Any]) -> str:
    scheme = str(environ.get("wsgi.url_scheme") or "").strip().lower()
    host = str(environ.get("HTTP_HOST") or "").strip().lower()
    if scheme not in {"http", "https"} or not _valid_exact_host(host):
        raise AppHostingError("The platform request does not provide one exact HTTP Host and scheme.")
    return _normalize_origin(f"{scheme}://{host}")


def _isolated_origin(environ: dict[str, Any], *, label: str, platform_origin: str) -> tuple[str, str, bool]:
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
        configured_origin = _normalize_origin(configured)
        if configured_origin != platform_origin or not platform_origin.startswith("https://"):
            raise AppHostingError("Hosted app-frame origins require the exact configured HTTPS platform origin.")
        host = f"{label}.sidecars.{domain}"
        return f"https://{host}", host, True
    raise AppHostingError("MAVERICK_SIDECAR_ORIGIN_MODE must be `local` or `hosted`.")


def _normalize_origin(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise AppHostingError("App-frame platform origin configuration is invalid.")
    if parsed.username is not None or parsed.password is not None:
        raise AppHostingError("App-frame platform origin configuration is invalid.")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _content_security_policy(platform_origin: str) -> str:
    return "; ".join(
        (
            "base-uri 'self'",
            "object-src 'none'",
            f"frame-ancestors 'self' {platform_origin}",
        )
    )


def _security_headers(binding: SidecarBrowserBinding) -> list[tuple[str, str]]:
    return [
        ("Cache-Control", "private, no-store"),
        ("Referrer-Policy", "no-referrer"),
        ("Content-Security-Policy", binding.content_security_policy),
        ("Cross-Origin-Resource-Policy", "same-origin"),
        ("Origin-Agent-Cluster", "?1"),
        ("X-Content-Type-Options", "nosniff"),
    ]


def _launch_headers() -> list[tuple[str, str]]:
    return [("Cache-Control", "no-store"), ("Referrer-Policy", "no-referrer")]


def _denial_headers() -> list[tuple[str, str]]:
    return [
        ("Cache-Control", "no-store"),
        ("Referrer-Policy", "no-referrer"),
        ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"),
        ("X-Content-Type-Options", "nosniff"),
    ]


def _session_cookie(value: str, *, secure: bool) -> str:
    secure_attribute = "; Secure" if secure else ""
    return (
        f"{APP_FRAME_COOKIE_NAME}={value}; Path=/; HttpOnly; SameSite=Strict; "
        f"Max-Age={SESSION_IDLE_TTL_SECONDS}{secure_attribute}"
    )


def _header_values(scope: dict[str, Any], name: bytes) -> list[str]:
    return [
        raw_value.decode("latin1").strip().lower()
        if name in {b"host", b"sec-fetch-site"}
        else raw_value.decode("latin1").strip()
        for raw_name, raw_value in scope.get("headers", [])
        if raw_name.lower() == name
    ]


def _valid_exact_host(value: str) -> bool:
    if not value or any(character.isspace() for character in value) or "," in value or "/" in value or "@" in value:
        return False
    try:
        parsed = urlsplit(f"//{value}")
        _ = parsed.port
    except ValueError:
        return False
    return bool(parsed.hostname)


def _looks_like_app_frame_host(value: str) -> bool:
    if not _valid_exact_host(value):
        return value.lower().startswith("af-") and ".sidecars." in value.lower()
    hostname = str(urlsplit(f"//{value}").hostname or "").lower()
    return hostname.startswith("af-") and ".sidecars." in hostname


def _cookie_value(header: str, name: str) -> str:
    matches: list[str] = []
    for part in header.split(";"):
        candidate, separator, value = part.strip().partition("=")
        if separator and candidate == name:
            matches.append(value)
    return matches[0] if len(matches) == 1 else ""


def _retained_app_cookies(header: str) -> str:
    retained: list[str] = []
    reserved = {APP_FRAME_COOKIE_NAME, SESSION_COOKIE}
    for part in header.split(";"):
        candidate, separator, _value = part.strip().partition("=")
        if separator and candidate and candidate not in reserved:
            retained.append(part.strip())
    return "; ".join(retained)


def _reserved_cookie(value: bytes) -> bool:
    name = value.decode("latin1").split("=", 1)[0].strip()
    return name in {APP_FRAME_COOKIE_NAME, SESSION_COOKIE}


def _rewrite_platform_location(value: bytes, binding: SidecarBrowserBinding) -> bytes:
    text = value.decode("latin1")
    if text == binding.platform_origin:
        return binding.origin.encode("latin1")
    if text.startswith(f"{binding.platform_origin}/"):
        return f"{binding.origin}{text[len(binding.platform_origin):]}".encode("latin1")
    return value


def _response_is_html(message: dict[str, Any]) -> bool:
    for name, value in message.get("headers", []):
        if bytes(name).lower() == b"content-type":
            return bytes(value).decode("latin1").split(";", 1)[0].strip().lower() == "text/html"
    return False


async def _read_bounded_body(receive: AsgiReceive, *, maximum: int) -> bytes | None:
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message.get("type") != "http.request":
            break
        chunk = bytes(message.get("body") or b"")
        size += len(chunk)
        if size > maximum:
            return None
        chunks.append(chunk)
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


async def _deny(send: AsgiSend, binding: SidecarBrowserBinding, reason: str, *, status: int = 401) -> None:
    await _send_json(send, {"error": reason}, status=status, headers=_security_headers(binding))


async def _send_json(
    send: AsgiSend,
    payload: dict[str, Any],
    *,
    status: int,
    headers: list[tuple[str, str]],
) -> None:
    body = json.dumps(payload, indent=2).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
                *[(name.lower().encode("latin1"), value.encode("latin1")) for name, value in headers],
            ],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})
