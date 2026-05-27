"""HTTP API for platform-owned secret management."""

from __future__ import annotations

from core.api.http import StartResponse, json_response, read_json_body
from core.api.platform_state import PlatformState
from core.api.secret_audit_records import record_cascaded_grant_revocations, record_secret_change
from core.api.secret_grant_admin import (
    create_secret_grant_from_payload,
    get_workspace_secret_grant,
    list_grant_payloads,
    list_secret_audit_payloads,
    list_secret_grant_recommendations,
    list_secret_grant_targets,
    revoke_workspace_secret_grant,
)
from core.api.secret_api_payloads import grant_payload, secret_payload
from core.api.session_api import RequestSession, require_session
from core.secrets.errors import SecretError
from core.secrets.service import (
    create_platform_secret,
    disable_platform_secret_with_revocations,
    resolve_app_secret_grant,
    revoke_platform_secret_with_revocations,
    rotate_platform_secret,
    update_platform_secret_metadata,
)


def handle_secret_api(state: PlatformState, environ: dict, start_response: StartResponse) -> list[bytes] | None:
    """Handle platform secret routes for Vault and operator workflows."""
    path = str(environ.get("PATH_INFO") or "/")
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    if not (
        path == "/api/secrets"
        or path.startswith("/api/secrets/")
        or path == "/api/secret-grants"
        or path.startswith("/api/secret-grants/")
        or path == "/api/secret-grant-needs"
        or path == "/api/secret-grant-targets"
        or path == "/api/secret-audit"
        or path == "/api/secret-use"
    ):
        return None

    context_or_response = require_session(state, environ, start_response)
    if not isinstance(context_or_response, RequestSession):
        return context_or_response
    context = context_or_response
    if context.user.platform_role != "admin":
        return json_response(start_response, {"error": "admin_required"}, status="403 Forbidden")

    try:
        if path == "/api/secrets":
            return _handle_secrets_collection(state, context, method, environ, start_response)
        if path.startswith("/api/secrets/"):
            return _handle_secret_record(
                state,
                context,
                path.removeprefix("/api/secrets/"),
                method,
                environ,
                start_response,
            )
        if path == "/api/secret-grants":
            return _handle_grants_collection(state, context, method, environ, start_response)
        if path.startswith("/api/secret-grants/"):
            return _handle_grant_record(
                state,
                context,
                path.removeprefix("/api/secret-grants/"),
                method,
                start_response,
            )
        if path == "/api/secret-grant-needs":
            return _handle_grant_needs(state, context, method, start_response)
        if path == "/api/secret-grant-targets":
            return _handle_grant_targets(state, context, method, start_response)
        if path == "/api/secret-audit":
            return _handle_secret_audit(state, context, method, start_response)
        if path == "/api/secret-use":
            return _handle_secret_use(state, context, method, environ, start_response)
    except SecretError as error:
        return json_response(start_response, {"error": "secret_error", "detail": str(error)}, status="400 Bad Request")
    return None


def _handle_grant_targets(
    state: PlatformState,
    context: RequestSession,
    method: str,
    start_response: StartResponse,
) -> list[bytes]:
    if method != "GET":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    return json_response(
        start_response,
        list_secret_grant_targets(state, workspace_id=context.workspace_id),
    )


def _handle_grant_needs(
    state: PlatformState,
    context: RequestSession,
    method: str,
    start_response: StartResponse,
) -> list[bytes]:
    if method != "GET":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    return json_response(
        start_response,
        {"items": list_secret_grant_recommendations(state, workspace_id=context.workspace_id)},
    )


def _handle_secrets_collection(
    state: PlatformState,
    context: RequestSession,
    method: str,
    environ: dict,
    start_response: StartResponse,
) -> list[bytes]:
    if method == "GET":
        return json_response(
            start_response,
            {"items": [secret_payload(item) for item in state.secret_store.list_secrets()]},
        )
    if method != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    body = read_json_body(environ)
    secret = create_platform_secret(
        state.secret_store,
        label=str(body.get("label") or "").strip(),
        raw_value=str(body.get("raw_value") or ""),
        alias=str(body.get("alias") or "").strip() or None,
        description=str(body.get("description") or "").strip() or None,
        kind=str(body.get("kind") or "generic"),
    )
    record_secret_change(
        state,
        context,
        action="core.secrets.create",
        detail=f"Created platform secret `{secret.secret_id}`.",
        payload={"secret_id": secret.secret_id, "alias": secret.alias},
    )
    return json_response(start_response, {"secret": secret_payload(secret)}, status="201 Created")


def _handle_secret_record(
    state: PlatformState,
    context: RequestSession,
    suffix: str,
    method: str,
    environ: dict,
    start_response: StartResponse,
) -> list[bytes]:
    secret_id, _, action = suffix.strip("/").partition("/")
    if not secret_id:
        return json_response(start_response, {"error": "missing_secret_id"}, status="400 Bad Request")
    if not action:
        if method == "GET":
            return json_response(start_response, {"secret": secret_payload(state.secret_store.get_secret(secret_id))})
        if method != "PATCH":
            return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
        body = read_json_body(environ)
        secret = update_platform_secret_metadata(
            state.secret_store,
            secret_id=secret_id,
            label=str(body.get("label") or "").strip(),
            alias=str(body.get("alias") or "").strip() or None,
            description=str(body.get("description") or "").strip() or None,
            kind=str(body.get("kind") or "generic"),
        )
        record_secret_change(
            state,
            context,
            action="core.secrets.update",
            detail=f"Updated platform secret `{secret.secret_id}` metadata.",
            payload={"secret_id": secret.secret_id, "alias": secret.alias},
        )
        return json_response(start_response, {"secret": secret_payload(secret)})
    if method != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    if action == "rotate":
        body = read_json_body(environ)
        secret = rotate_platform_secret(
            state.secret_store,
            secret_id=secret_id,
            raw_value=str(body.get("raw_value") or ""),
        )
        revoked_grants = []
    elif action == "disable":
        result = disable_platform_secret_with_revocations(state.secret_store, secret_id=secret_id)
        secret = result.secret
        revoked_grants = result.revoked_grants
    elif action == "revoke":
        result = revoke_platform_secret_with_revocations(state.secret_store, secret_id=secret_id)
        secret = result.secret
        revoked_grants = result.revoked_grants
    else:
        return json_response(start_response, {"error": "not_found"}, status="404 Not Found")
    record_secret_change(
        state,
        context,
        action=f"core.secrets.{action}",
        detail=f"Applied `{action}` to platform secret `{secret.secret_id}`.",
        payload={"secret_id": secret.secret_id, "revoked_grant_count": len(revoked_grants)},
    )
    record_cascaded_grant_revocations(state, context, secret_id=secret.secret_id, grants=revoked_grants)
    return json_response(
        start_response,
        {"secret": secret_payload(secret), "revoked_grant_count": len(revoked_grants)},
    )


def _handle_grants_collection(
    state: PlatformState,
    context: RequestSession,
    method: str,
    environ: dict,
    start_response: StartResponse,
) -> list[bytes]:
    if method == "GET":
        return json_response(
            start_response,
            {"items": list_grant_payloads(state, workspace_id=context.workspace_id)},
        )
    if method != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    grant, secret = create_secret_grant_from_payload(
        state,
        workspace_id=context.workspace_id,
        payload=read_json_body(environ),
        created_by_user_id=context.user.user_id,
    )
    record_secret_change(
        state,
        context,
        action="core.secrets.grant.create",
        detail=f"Created secret grant `{grant.grant_id}` for app `{grant.app_id}`.",
        payload={
            "grant_id": grant.grant_id,
            "app_id": grant.app_id,
            "secret_id": secret.secret_id,
            "secret_ref": grant.secret_ref,
        },
    )
    return json_response(start_response, {"grant": grant_payload(grant, state=state)}, status="201 Created")


def _handle_grant_record(
    state: PlatformState,
    context: RequestSession,
    suffix: str,
    method: str,
    start_response: StartResponse,
) -> list[bytes]:
    grant_id, _, action = suffix.strip("/").partition("/")
    if method == "GET" and not action:
        grant = get_workspace_secret_grant(state, grant_id=grant_id, workspace_id=context.workspace_id)
        return json_response(start_response, {"grant": grant_payload(grant, state=state)})
    if method == "POST" and action == "revoke":
        grant = revoke_workspace_secret_grant(state, grant_id=grant_id, workspace_id=context.workspace_id)
        record_secret_change(
            state,
            context,
            action="core.secrets.grant.revoke",
            detail=f"Revoked secret grant `{grant.grant_id}`.",
            payload={"grant_id": grant.grant_id, "app_id": grant.app_id},
        )
        return json_response(start_response, {"grant": grant_payload(grant, state=state)})
    return json_response(start_response, {"error": "not_found"}, status="404 Not Found")


def _handle_secret_audit(
    state: PlatformState,
    context: RequestSession,
    method: str,
    start_response: StartResponse,
) -> list[bytes]:
    if method != "GET":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    return json_response(
        start_response,
        {"items": list_secret_audit_payloads(state, workspace_id=context.workspace_id)},
    )


def _handle_secret_use(
    state: PlatformState,
    context: RequestSession,
    method: str,
    environ: dict,
    start_response: StartResponse,
) -> list[bytes]:
    if method != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    body = read_json_body(environ)
    lease = resolve_app_secret_grant(
        state.secret_store,
        workspace_id=context.workspace_id,
        app_id=str(body.get("app_id") or "").strip(),
        grant_id=str(body.get("grant_id") or "").strip(),
        action=str(body.get("action") or "").strip(),
        target=str(body.get("target") or "").strip() or None,
        actor_user_id=context.user.user_id,
        observability_store=state.observability_store,
    )
    return json_response(
        start_response,
        {
            "lease": {
                "lease_id": lease.lease_id,
                "secret_id": lease.secret_id,
                "source_grant_id": lease.source_grant_id,
                "redacted_value": lease.redacted_value,
                "issued_at": lease.issued_at,
            }
        },
    )
