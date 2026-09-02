"""HTTP API for registry-driven app widget discovery and mounting."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.api.app_mounts import is_public_app_static_asset, serve_frontend
from core.api.http import StartResponse, json_response, query_params, read_json_body, text_response
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession, require_session
from core.api.widget_context import sign_widget_context, verify_widget_context
from core.apps.widgets import list_workspace_widgets, resolve_workspace_widget
from core.observability.service import record_platform_audit, record_platform_event


def _record_widget_event(
    state: PlatformState,
    *,
    event_type: str,
    workspace_id: str,
    app_id: str | None,
    payload: dict,
) -> None:
    record_platform_event(
        state.observability_store,
        event_type=event_type,
        event_plane="app",
        source_domain="apps.widgets",
        workspace_id=workspace_id,
        app_id=app_id,
        payload=payload,
    )


def _require_widget_session(state: PlatformState, environ: dict, start_response: StartResponse) -> RequestSession | list[bytes]:
    return require_session(state, environ, start_response)


def _context_payload(*, context: RequestSession, body: dict[str, Any]) -> dict[str, Any]:
    content = body.get("content") if isinstance(body.get("content"), dict) else {}
    return {
        "workspace_id": context.workspace_id,
        "user_id": context.user.user_id,
        "host_app_id": str(body.get("host_app_id") or ""),
        "owner_app_id": str(body.get("owner_app_id") or ""),
        "widget_id": str(body.get("widget_id") or ""),
        "message_id": str(body.get("message_id") or ""),
        "content": content,
    }


def handle_widget_api(
    state: PlatformState,
    environ: dict,
    start_response: StartResponse,
    *,
    start_path: Path,
    workspace_id: str = "default",
) -> list[bytes] | None:
    """Handle widget discovery, context, and frontend routes."""
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    if not path.startswith("/api/apps/widgets"):
        return None

    public_widget_static_asset = _public_widget_static_asset_subpath(path, method)
    context: RequestSession | None = None
    if not public_widget_static_asset:
        context_or_response = _require_widget_session(state, environ, start_response)
        if not isinstance(context_or_response, RequestSession):
            return context_or_response
        context = context_or_response
        workspace_id = context.workspace_id

    if path == "/api/apps/widgets" and method == "GET":
        if context is None:
            return json_response(start_response, {"error": "authentication_required"}, status="401 Unauthorized")
        query = query_params(environ)
        items = list_workspace_widgets(
            state.app_store,
            workspace_id=workspace_id,
            workspace_store=state.workspace_store,
            user=context.user,
            host=query.get("host"),
            content_kind=query.get("content_kind"),
            start_path=start_path,
        )
        _record_widget_event(
            state,
            event_type="apps.widgets.lookup",
            workspace_id=workspace_id,
            app_id=None,
            payload={"host": query.get("host"), "content_kind": query.get("content_kind"), "count": len(items)},
        )
        return json_response(start_response, {"items": [serialize_widget_registry_item(item) for item in items]})

    if path == "/api/apps/widgets/context" and method == "POST":
        if context is None:
            return json_response(start_response, {"error": "authentication_required"}, status="401 Unauthorized")
        body = read_json_body(environ)
        payload = _context_payload(context=context, body=body)
        resolved = resolve_workspace_widget(
            state.app_store,
            workspace_id=context.workspace_id,
            owner_app_id=payload["owner_app_id"],
            widget_id=payload["widget_id"],
            workspace_store=state.workspace_store,
            user=context.user,
            start_path=start_path,
        )
        if resolved is None:
            record_platform_audit(
                state.observability_store,
                action="apps.widgets.context",
                status="denied",
                source_domain="apps.widgets",
                detail="Denied widget context creation for unavailable widget.",
                workspace_id=context.workspace_id,
                app_id=payload["owner_app_id"],
                payload={"owner_app_id": payload["owner_app_id"], "widget_id": payload["widget_id"]},
            )
            return json_response(start_response, {"error": "widget_not_available"}, status="404 Not Found")
        content_kind = payload["content"].get("kind") if isinstance(payload["content"], dict) else None
        if payload["host_app_id"] != resolved.widget.host or content_kind not in resolved.widget.content_kinds:
            record_platform_audit(
                state.observability_store,
                action="apps.widgets.context",
                status="denied",
                source_domain="apps.widgets",
                detail="Denied widget context creation for incompatible host surface or content kind.",
                workspace_id=context.workspace_id,
                app_id=payload["owner_app_id"],
                payload={
                    "owner_app_id": payload["owner_app_id"],
                    "widget_id": payload["widget_id"],
                    "host_app_id": payload["host_app_id"],
                    "content_kind": content_kind,
                },
            )
            return json_response(start_response, {"error": "widget_not_compatible"}, status="403 Forbidden")
        token = sign_widget_context(payload)
        _record_widget_event(
            state,
            event_type="apps.widgets.context.created",
            workspace_id=context.workspace_id,
            app_id=payload["owner_app_id"],
            payload={
                "owner_app_id": payload["owner_app_id"],
                "widget_id": payload["widget_id"],
                "host_app_id": payload["host_app_id"],
            },
        )
        return json_response(start_response, {"context_token": token, "context": payload})

    if path.startswith("/api/apps/widgets/context/") and method == "GET":
        if context is None:
            return json_response(start_response, {"error": "authentication_required"}, status="401 Unauthorized")
        token = path.removeprefix("/api/apps/widgets/context/").strip("/")
        payload = verify_widget_context(token)
        if payload is None or payload.get("workspace_id") != context.workspace_id:
            return json_response(start_response, {"error": "invalid_widget_context"}, status="403 Forbidden")
        return json_response(start_response, {"context": payload})

    if path.startswith("/api/apps/widgets/") and "/frontend" in path and method in {"GET", "HEAD"}:
        if (
            not public_widget_static_asset
            and environ.get("maverick.app_frame_proxy") is not True
        ):
            return json_response(
                start_response,
                {"error": "app_frame_isolation_required"},
                status="403 Forbidden",
            )
        remainder = path.removeprefix("/api/apps/widgets/")
        owner_app_id, _, tail = remainder.partition("/")
        widget_id, _, subpath = tail.partition("/frontend")
        resolved = resolve_workspace_widget(
            state.app_store,
            workspace_id=workspace_id,
            owner_app_id=owner_app_id,
            widget_id=widget_id,
            workspace_store=None if public_widget_static_asset else state.workspace_store,
            user=None if context is None else context.user,
            start_path=start_path,
        )
        if resolved is None:
            record_platform_audit(
                state.observability_store,
                action="apps.widgets.mount",
                status="denied",
                source_domain="apps.widgets",
                detail="Denied widget mount for unavailable widget.",
                workspace_id=workspace_id,
                app_id=owner_app_id,
                payload={"owner_app_id": owner_app_id, "widget_id": widget_id},
            )
            return text_response(start_response, "Widget not found", status="404 Not Found")
        _record_widget_event(
            state,
            event_type="apps.widgets.mounted",
            workspace_id=workspace_id,
            app_id=owner_app_id,
            payload={"owner_app_id": owner_app_id, "widget_id": widget_id},
        )
        return serve_frontend(
            start_response,
            frontend_root=(resolved.source_root / resolved.widget.frontend.mount).resolve(),
            subpath=subpath,
            spa_fallback=resolved.widget.frontend.spa_fallback and not public_widget_static_asset,
            cross_origin=public_widget_static_asset,
            environ=environ,
        )

    return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")


def _public_widget_static_asset_subpath(path: str, method: str) -> bool:
    if method not in {"GET", "HEAD"} or not path.startswith("/api/apps/widgets/") or "/frontend" not in path:
        return False
    _prefix, _separator, subpath = path.partition("/frontend")
    return is_public_app_static_asset(subpath)


def serialize_widget_registry_item(item: Any) -> dict[str, Any]:
    """Serialize public widget registry metadata without context capabilities."""
    return {
        "owner_app_id": item.owner_app_id,
        "widget_id": item.widget_id,
        "host": item.host,
        "content_kinds": list(item.content_kinds),
        "frontend_mount": item.frontend_mount,
        "actions": dict(item.actions),
    }
