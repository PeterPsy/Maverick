"""Host-routed isolated browser origins for generic app-owned sidecars."""

from __future__ import annotations

from hashlib import sha256
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, urlsplit

from core.api.http import StartResponse, json_response, read_json_body
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession
from core.api.sidecar_proxy import (
    AuthorizedSidecarTarget,
    current_sidecar_instance_id,
    ensure_authorized_sidecar_running,
    handle_app_sidecar_proxy_asgi,
    resolve_authorized_sidecar,
)
from core.apps.errors import AppHostingError
from core.apps.sidecar_browser_sessions import (
    MAX_TICKET_TTL_SECONDS,
    SESSION_IDLE_TTL_SECONDS,
    SIDECAR_BROWSER_COOKIE_NAME,
    SidecarBrowserBinding,
    SidecarBrowserSession,
)
from core.identity.errors import UserNotFoundError
from core.observability.service import record_platform_audit
from core.shared.entrypoints import EntrypointShutdownController


AsgiReceive = Callable[[], Awaitable[dict[str, Any]]]
AsgiSend = Callable[[dict[str, Any]], Awaitable[None]]
BROWSER_LAUNCH_PATH = "/api/app-sidecars/browser-launch"
BROWSER_BOOTSTRAP_PATH = "/.well-known/maverick-sidecar-bootstrap"
_MAX_BOOTSTRAP_BODY_BYTES = 4096
_DOMAIN_PATTERN = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def handle_sidecar_browser_launch(
    state: PlatformState,
    context: RequestSession | None,
    environ: dict,
    start_response: StartResponse,
    *,
    start_path: Path,
    shutdown_controller: EntrypointShutdownController | None,
) -> list[bytes] | None:
    """Issue a one-shot form ticket on the authenticated platform origin."""
    path = str(environ.get("PATH_INFO") or "/")
    if path != BROWSER_LAUNCH_PATH:
        return None
    if str(environ.get("REQUEST_METHOD") or "GET").upper() != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    if context is None:
        return json_response(start_response, {"error": "authentication_required"}, status="401 Unauthorized")
    body = read_json_body(environ)
    if set(body) - {"app_id", "sidecar_id", "path"}:
        return json_response(start_response, {"error": "invalid_sidecar_launch_request"}, status="400 Bad Request")
    app_id = str(body.get("app_id") or "").strip()
    sidecar_id = str(body.get("sidecar_id") or "").strip()
    try:
        clean_path = _clean_redirect_path(body.get("path", "/index.html"))
    except AppHostingError as error:
        return json_response(
            start_response,
            {"error": "invalid_sidecar_launch_request", "detail": str(error)},
            status="400 Bad Request",
        )
    target, error = resolve_authorized_sidecar(
        state,
        workspace_id=context.workspace_id,
        app_id=app_id,
        sidecar_id=sidecar_id,
        user=context.user,
        start_path=start_path,
    )
    if error is not None:
        return json_response(start_response, error.payload, status=error.status)
    assert target is not None
    if target.sidecar.browser_origin is None:
        return json_response(start_response, {"error": "sidecar_browser_origin_not_declared"}, status="404 Not Found")
    try:
        origin, host, platform_origin, secure = _resolve_origin_configuration(environ, target=target)
        running = ensure_authorized_sidecar_running(
            target,
            start_path=start_path,
            shutdown_controller=shutdown_controller,
        )
    except AppHostingError as error:
        return json_response(
            start_response,
            {"error": "sidecar_origin_unavailable", "detail": str(error)},
            status="503 Service Unavailable",
            headers=_platform_launch_headers(),
        )
    generation_id = _generation_id(target)
    binding = SidecarBrowserBinding(
        actor_user_id=context.user.user_id,
        workspace_id=target.binding.workspace_id,
        app_id=target.binding.app_id,
        sidecar_id=target.sidecar.service_id,
        host=host,
        origin=origin,
        platform_origin=platform_origin,
        generation_id=generation_id,
        sidecar_instance_id=running.instance_id,
        clean_path=clean_path,
        secure=secure,
        content_security_policy=_content_security_policy(platform_origin),
    )
    ticket = state.sidecar_browser_sessions.issue_ticket(binding)
    record_platform_audit(
        state.observability_store,
        action="sidecar.browser_ticket.issue",
        status="succeeded",
        source_domain="apps.sidecars.browser",
        detail=f"Issued an isolated browser launch ticket for app `{binding.app_id}`.",
        workspace_id=binding.workspace_id,
        app_id=binding.app_id,
        payload={
            "sidecar_id": binding.sidecar_id,
            "sidecar_host": binding.host,
            "generation_id": binding.generation_id,
            "actor_user_id": binding.actor_user_id,
            "expires_in_seconds": MAX_TICKET_TTL_SECONDS,
        },
    )
    return json_response(
        start_response,
        {
            "origin": origin,
            "bootstrap_url": f"{origin}{BROWSER_BOOTSTRAP_PATH}",
            "method": "POST",
            "ticket_field": "ticket",
            "ticket": ticket.value,
            "expires_in_seconds": MAX_TICKET_TTL_SECONDS,
        },
        headers=_platform_launch_headers(),
    )


def is_reserved_sidecar_browser_host(scope: dict[str, Any]) -> bool:
    """Return whether ASGI must not fall through to the normal platform host."""
    values = _header_values(scope, b"host")
    return any(_looks_like_sidecar_host(value) for value in values)


async def handle_sidecar_browser_origin(
    state: PlatformState,
    *,
    scope: dict[str, Any],
    receive: AsgiReceive,
    send: AsgiSend,
    start_path: Path,
    shutdown_controller: EntrypointShutdownController | None,
) -> None:
    """Serve one host-bound sidecar browser request without platform fallback."""
    hosts = _header_values(scope, b"host")
    if len(hosts) != 1 or not _valid_exact_host(hosts[0]):
        await _send_json(send, {"error": "sidecar_host_invalid"}, status=421, headers=_denial_headers())
        return
    host = hosts[0].lower()
    path = str(scope.get("path") or "/")
    method = str(scope.get("method") or "GET").upper()
    if path == BROWSER_BOOTSTRAP_PATH:
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

    cookies = _header_values(scope, b"cookie")
    if len(cookies) > 1:
        await _deny(state, send, host=host, reason="ambiguous_cookie")
        return
    token = _cookie_value(cookies[0] if cookies else "", SIDECAR_BROWSER_COOKIE_NAME)
    session = state.sidecar_browser_sessions.validate(token, host=host) if token else None
    if session is None:
        await _deny(state, send, host=host, reason="session_required")
        return
    current, current_error = _current_target(state, session, start_path=start_path)
    if current is None:
        state.sidecar_browser_sessions.revoke_sidecar(
            workspace_id=session.binding.workspace_id,
            app_id=session.binding.app_id,
            sidecar_id=session.binding.sidecar_id,
        )
        await _deny(
            state,
            send,
            host=host,
            reason=current_error,
            binding=session.binding,
            status=401,
        )
        return
    if method not in _SAFE_METHODS:
        origin_values = _header_values(scope, b"origin")
        fetch_site_values = _header_values(scope, b"sec-fetch-site")
        if origin_values != [session.binding.origin] or fetch_site_values != ["same-origin"]:
            await _deny(
                state,
                send,
                host=host,
                reason="csrf_proof_required",
                binding=session.binding,
                status=403,
            )
            return
    validated = state.sidecar_browser_sessions.validate_and_touch(token, host=host)
    if validated is None:
        await _deny(state, send, host=host, reason="session_expired")
        return
    headers = _security_headers(validated.session.binding)
    if validated.rotated_value is not None:
        headers.append(("Set-Cookie", _session_cookie(validated.rotated_value, secure=session.binding.secure)))
    response_status: int | None = None

    async def audited_send(message: dict[str, Any]) -> None:
        nonlocal response_status
        if message.get("type") == "http.response.start":
            response_status = int(message.get("status") or 0)
        await send(message)

    try:
        await handle_app_sidecar_proxy_asgi(
            state,
            scope=scope,
            receive=receive,
            send=audited_send,
            workspace_id=current.binding.workspace_id,
            app_id=current.binding.app_id,
            sidecar_id=current.sidecar.service_id,
            subpath=path.lstrip("/"),
            user=state.identity_store.get_user(session.binding.actor_user_id),
            start_path=start_path,
            shutdown_controller=shutdown_controller,
            enforced_response_headers=headers,
            expected_instance_id=session.binding.sidecar_instance_id,
        )
    except BaseException:
        _record_browser_request(state, binding=session.binding, method=method, response_status=response_status)
        raise
    _record_browser_request(state, binding=session.binding, method=method, response_status=response_status)


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
        await _deny(state, send, host=host, reason="bootstrap_url_must_be_clean", status=400)
        return
    content_types = _header_values(scope, b"content-type")
    if len(content_types) != 1 or content_types[0].split(";", 1)[0].strip().lower() != "application/x-www-form-urlencoded":
        await _deny(state, send, host=host, reason="bootstrap_form_required", status=400)
        return
    body = await _read_bounded_body(receive, maximum=_MAX_BOOTSTRAP_BODY_BYTES)
    if body is None:
        await _deny(state, send, host=host, reason="bootstrap_body_too_large", status=413)
        return
    try:
        fields = parse_qs(body.decode("utf-8"), keep_blank_values=True, strict_parsing=True)
    except (UnicodeDecodeError, ValueError):
        fields = {}
    ticket_values = fields.get("ticket", [])
    if set(fields) != {"ticket"} or len(ticket_values) != 1 or not ticket_values[0]:
        await _deny(state, send, host=host, reason="bootstrap_ticket_invalid", status=400)
        return
    issued = state.sidecar_browser_sessions.consume_ticket(ticket_values[0], host=host)
    if issued is None:
        await _deny(state, send, host=host, reason="bootstrap_ticket_expired_or_spent", status=410)
        return
    current, current_error = _current_target(state, issued.session, start_path=start_path)
    if current is None:
        state.sidecar_browser_sessions.revoke_sidecar(
            workspace_id=issued.session.binding.workspace_id,
            app_id=issued.session.binding.app_id,
            sidecar_id=issued.session.binding.sidecar_id,
        )
        await _deny(
            state,
            send,
            host=host,
            reason=current_error,
            binding=issued.session.binding,
            status=410,
        )
        return
    binding = issued.session.binding
    headers = _security_headers(binding)
    headers.extend(
        [
            ("Location", binding.clean_path),
            ("Set-Cookie", _session_cookie(issued.value, secure=binding.secure)),
        ]
    )
    record_platform_audit(
        state.observability_store,
        action="sidecar.browser_session.bootstrap",
        status="succeeded",
        source_domain="apps.sidecars.browser",
        detail=f"Created an isolated browser session for app `{binding.app_id}`.",
        workspace_id=binding.workspace_id,
        app_id=binding.app_id,
        payload={
            "sidecar_id": binding.sidecar_id,
            "sidecar_host": binding.host,
            "generation_id": binding.generation_id,
            "actor_user_id": binding.actor_user_id,
        },
    )
    await send(
        {
            "type": "http.response.start",
            "status": 303,
            "headers": [(name.lower().encode("latin1"), value.encode("latin1")) for name, value in headers],
        }
    )
    await send({"type": "http.response.body", "body": b"", "more_body": False})


def _current_target(
    state: PlatformState,
    session: SidecarBrowserSession,
    *,
    start_path: Path,
) -> tuple[AuthorizedSidecarTarget | None, str]:
    binding = session.binding
    try:
        user = state.identity_store.get_user(binding.actor_user_id)
    except UserNotFoundError:
        return None, "actor_unavailable"
    if not user.is_active:
        return None, "actor_unavailable"
    target, error = resolve_authorized_sidecar(
        state,
        workspace_id=binding.workspace_id,
        app_id=binding.app_id,
        sidecar_id=binding.sidecar_id,
        user=user,
        start_path=start_path,
    )
    if target is None:
        return None, str((error.payload if error is not None else {}).get("error") or "sidecar_unavailable")
    if target.sidecar.browser_origin is None or _generation_id(target) != binding.generation_id:
        return None, "sidecar_generation_changed"
    if current_sidecar_instance_id(target) != binding.sidecar_instance_id:
        return None, "sidecar_restarted"
    return target, ""


def _resolve_origin_configuration(
    environ: dict,
    *,
    target: AuthorizedSidecarTarget,
) -> tuple[str, str, str, bool]:
    mode = os.environ.get("MAVERICK_SIDECAR_ORIGIN_MODE", "local").strip().lower() or "local"
    if mode == "local":
        platform_origin = _request_platform_origin(environ)
        parsed = urlsplit(platform_origin)
        if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} and not str(parsed.hostname or "").endswith(
            ".localhost"
        ):
            raise AppHostingError("Local sidecar origins require the platform to be accessed through localhost.")
        suffix = f":{parsed.port}" if parsed.port is not None else ""
        host = f"{_opaque_label(target)}.sidecars.localhost{suffix}"
        return f"{parsed.scheme}://{host}", host, platform_origin, parsed.scheme == "https"
    if mode == "hosted":
        domain = os.environ.get("MAVERICK_SIDECAR_INSTALLATION_DOMAIN", "").strip().lower().rstrip(".")
        configured_platform_origin = os.environ.get("MAVERICK_SIDECAR_PLATFORM_ORIGIN", "").strip()
        if not domain or not _DOMAIN_PATTERN.fullmatch(domain) or not configured_platform_origin:
            raise AppHostingError(
                "Hosted sidecar origins require MAVERICK_SIDECAR_INSTALLATION_DOMAIN and MAVERICK_SIDECAR_PLATFORM_ORIGIN."
            )
        platform_origin = _normalize_origin(configured_platform_origin)
        if not platform_origin.startswith("https://") or _request_platform_origin(environ) != platform_origin:
            raise AppHostingError("Hosted sidecar origins require the exact configured HTTPS platform origin.")
        host = f"{_opaque_label(target)}.sidecars.{domain}"
        return f"https://{host}", host, platform_origin, True
    raise AppHostingError("MAVERICK_SIDECAR_ORIGIN_MODE must be `local` or `hosted`.")


def _request_platform_origin(environ: dict) -> str:
    scheme = str(environ.get("wsgi.url_scheme") or "").strip().lower()
    host = str(environ.get("HTTP_HOST") or "").strip().lower()
    if scheme not in {"http", "https"} or not _valid_exact_host(host):
        raise AppHostingError("The platform request does not provide one exact HTTP Host and scheme.")
    return _normalize_origin(f"{scheme}://{host}")


def _normalize_origin(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise AppHostingError("Sidecar platform origin configuration is invalid.")
    if parsed.username is not None or parsed.password is not None:
        raise AppHostingError("Sidecar platform origin configuration is invalid.")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _opaque_label(target: AuthorizedSidecarTarget) -> str:
    identity = "\0".join(
        (
            target.binding.workspace_id,
            target.binding.app_id,
            target.sidecar.service_id,
            _generation_id(target),
        )
    ).encode("utf-8")
    return f"sc-{sha256(identity).hexdigest()[:24]}"


def _generation_id(target: AuthorizedSidecarTarget) -> str:
    identity = "\0".join(
        (
            target.binding.binding_id,
            target.binding.source_record_id,
            target.binding.active_version,
            target.binding.data_root,
        )
    ).encode("utf-8")
    return sha256(identity).hexdigest()


def _content_security_policy(platform_origin: str) -> str:
    return "; ".join(
        (
            "default-src 'self'",
            "base-uri 'self'",
            "object-src 'none'",
            "script-src 'self' 'unsafe-inline'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob:",
            "font-src 'self' data:",
            "connect-src 'self'",
            "worker-src 'self' blob:",
            f"frame-ancestors {platform_origin}",
            "form-action 'self'",
        )
    )


def _security_headers(binding: SidecarBrowserBinding) -> list[tuple[str, str]]:
    return [
        ("Cache-Control", "no-store"),
        ("Referrer-Policy", "no-referrer"),
        ("Content-Security-Policy", binding.content_security_policy),
        ("Cross-Origin-Resource-Policy", "same-origin"),
        ("X-Content-Type-Options", "nosniff"),
    ]


def _platform_launch_headers() -> list[tuple[str, str]]:
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
        f"{SIDECAR_BROWSER_COOKIE_NAME}={value}; Path=/; HttpOnly; SameSite=Strict; "
        f"Max-Age={SESSION_IDLE_TTL_SECONDS}{secure_attribute}"
    )


def _clean_redirect_path(value: object) -> str:
    path = str(value or "").strip()
    if (
        not path.startswith("/")
        or path.startswith("//")
        or "\\" in path
        or "?" in path
        or "#" in path
        or any(ord(character) < 32 for character in path)
        or any(part in {".", ".."} for part in PurePosixPath(path).parts)
    ):
        raise AppHostingError("Sidecar launch path must be a clean absolute browser path.")
    return path


def _header_values(scope: dict[str, Any], name: bytes) -> list[str]:
    return [
        raw_value.decode("latin1").strip().lower() if name in {b"host", b"sec-fetch-site"} else raw_value.decode("latin1").strip()
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


def _looks_like_sidecar_host(value: str) -> bool:
    if not _valid_exact_host(value):
        return ".sidecars." in value.lower()
    hostname = str(urlsplit(f"//{value}").hostname or "").lower()
    return hostname.endswith(".sidecars.localhost") or ".sidecars." in hostname


def _cookie_value(header: str, name: str) -> str:
    matches: list[str] = []
    for part in header.split(";"):
        candidate, separator, value = part.strip().partition("=")
        if separator and candidate == name:
            matches.append(value)
    return matches[0] if len(matches) == 1 else ""


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


async def _deny(
    state: PlatformState,
    send: AsgiSend,
    *,
    host: str,
    reason: str,
    binding: SidecarBrowserBinding | None = None,
    status: int = 401,
) -> None:
    record_platform_audit(
        state.observability_store,
        action="sidecar.browser_request.deny",
        status="failed",
        source_domain="apps.sidecars.browser",
        detail="Denied an isolated sidecar browser request.",
        workspace_id=None if binding is None else binding.workspace_id,
        app_id=None if binding is None else binding.app_id,
        payload={
            "sidecar_id": None if binding is None else binding.sidecar_id,
            "sidecar_host": host,
            "reason": reason,
        },
    )
    await _send_json(
        send,
        {"error": reason},
        status=status,
        headers=_denial_headers() if binding is None else _security_headers(binding),
    )


def _record_browser_request(
    state: PlatformState,
    *,
    binding: SidecarBrowserBinding,
    method: str,
    response_status: int | None,
) -> None:
    succeeded = response_status is not None and response_status < 400
    record_platform_audit(
        state.observability_store,
        action="sidecar.browser_request.proxy",
        status="succeeded" if succeeded else "failed",
        source_domain="apps.sidecars.browser",
        detail="Proxied an isolated sidecar browser request." if succeeded else "An isolated sidecar browser request failed.",
        workspace_id=binding.workspace_id,
        app_id=binding.app_id,
        payload={
            "sidecar_id": binding.sidecar_id,
            "sidecar_host": binding.host,
            "method": method,
            "response_status": response_status,
        },
    )


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
