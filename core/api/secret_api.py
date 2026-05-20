"""HTTP API for platform-owned secret management."""

from __future__ import annotations

import logging
from pathlib import Path

from core.apps.errors import AppHostingError
from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.api.http import StartResponse, json_response, read_json_body
from core.api.platform_state import PlatformState
from core.api.secret_audit_records import record_cascaded_grant_revocations, record_secret_change
from core.api.secret_api_payloads import audit_payload, grant_payload, secret_payload
from core.api.secret_grant_validation import (
    assert_app_backend_logical_name_declared,
    assert_enabled_workspace_app,
    assert_logical_name_available,
    get_active_secret_for_ref,
    parse_expires_at,
    revoke_grants_for_secret,
)
from core.api.session_api import RequestSession, require_session
from core.secrets.app_delivery import assert_app_backend_targets_deliverable
from core.secrets.errors import SecretError, SecretPolicyError
from core.secrets.models import SecretGrantRecord
from core.secrets.service import (
    build_secret_ref,
    create_platform_secret,
    disable_platform_secret,
    grant_app_secret_use,
    resolve_app_secret_grant,
    revoke_app_secret_grant,
    revoke_platform_secret,
    rotate_platform_secret,
)


logger = logging.getLogger(__name__)


def handle_secret_api(state: PlatformState, environ: dict, start_response: StartResponse) -> list[bytes] | None:
    """Handle platform secret routes for Vault and operator workflows."""
    path = str(environ.get("PATH_INFO") or "/")
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    if not (
        path == "/api/secrets"
        or path.startswith("/api/secrets/")
        or path == "/api/secret-grants"
        or path.startswith("/api/secret-grants/")
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
            return _handle_secret_record(state, context, path.removeprefix("/api/secrets/"), method, environ, start_response)
        if path == "/api/secret-grants":
            return _handle_grants_collection(state, context, method, environ, start_response)
        if path.startswith("/api/secret-grants/"):
            return _handle_grant_record(state, context, path.removeprefix("/api/secret-grants/"), method, start_response)
        if path == "/api/secret-grant-targets":
            return _handle_grant_targets(state, context, method, start_response, start_path=state.repository_root)
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
    *,
    start_path: Path,
) -> list[bytes]:
    if method != "GET":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    items: list[dict[str, object]] = []
    for binding in enabled_workspace_app_bindings(state.app_store, workspace_id=context.workspace_id):
        try:
            _source_root, parsed = resolve_workspace_app_surface(state.app_store, binding=binding, start_path=start_path)
        except AppHostingError:
            continue
        except Exception:
            logger.exception(
                "Skipping enabled app `%s` in workspace `%s` while listing secret grant targets.",
                binding.app_id,
                context.workspace_id,
            )
            continue
        logical_names = sorted({str(item).strip().lower() for item in parsed.contract.permissions.secrets.read if str(item).strip()})
        if not logical_names:
            continue
        items.append(
            {
                "app_id": binding.app_id,
                "public_app_id": binding.public_app_id or parsed.app_id,
                "mount_app_id": binding.mount_app_id or binding.app_id,
                "name": parsed.name,
                "status": binding.status,
                "logical_names": logical_names,
            }
        )
    return json_response(start_response, {"items": items})


def _handle_secrets_collection(
    state: PlatformState,
    context: RequestSession,
    method: str,
    environ: dict,
    start_response: StartResponse,
) -> list[bytes]:
    if method == "GET":
        return json_response(start_response, {"items": [secret_payload(item) for item in state.secret_store.list_secrets()]})
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
        if method != "GET":
            return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
        return json_response(start_response, {"secret": secret_payload(state.secret_store.get_secret(secret_id))})
    if method != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    if action == "rotate":
        body = read_json_body(environ)
        secret = rotate_platform_secret(state.secret_store, secret_id=secret_id, raw_value=str(body.get("raw_value") or ""))
        revoked_grants = []
    elif action == "disable":
        secret = disable_platform_secret(state.secret_store, secret_id=secret_id)
        revoked_grants = revoke_grants_for_secret(state, secret=secret)
    elif action == "revoke":
        secret = revoke_platform_secret(state.secret_store, secret_id=secret_id)
        revoked_grants = revoke_grants_for_secret(state, secret=secret)
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
            {
                "items": [
                    grant_payload(item, state=state)
                    for item in state.secret_store.list_secret_grants(workspace_id=context.workspace_id)
                ]
            },
        )
    if method != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    body = read_json_body(environ)
    secret_ref = str(body.get("secret_ref") or "").strip()
    if not secret_ref:
        secret_id = str(body.get("secret_id") or "").strip() or None
        alias = str(body.get("alias") or "").strip() or None
        secret_ref = build_secret_ref(secret_id=secret_id, alias=alias)
    secret = get_active_secret_for_ref(state, secret_ref=secret_ref)
    app_id = str(body.get("app_id") or "").strip()
    logical_name = str(body.get("logical_name") or "").strip().lower()
    actions = [str(item) for item in body.get("actions", [])] if isinstance(body.get("actions"), list) else []
    target_patterns = [str(item) for item in body.get("target_patterns", [])] if isinstance(body.get("target_patterns"), list) else None
    assert_enabled_workspace_app(state, workspace_id=context.workspace_id, app_id=app_id)
    assert_logical_name_available(state, workspace_id=context.workspace_id, app_id=app_id, logical_name=logical_name)
    assert_app_backend_logical_name_declared(
        state,
        workspace_id=context.workspace_id,
        app_id=app_id,
        logical_name=logical_name,
        actions=actions,
    )
    assert_app_backend_targets_deliverable(actions, target_patterns)
    grant = grant_app_secret_use(
        state.secret_store,
        workspace_id=context.workspace_id,
        app_id=app_id,
        logical_name=logical_name,
        secret_ref=secret_ref,
        actions=actions,
        target_patterns=target_patterns,
        expires_at=parse_expires_at(body.get("expires_at")),
        created_by_user_id=context.user.user_id,
        reason=str(body.get("reason") or "").strip() or None,
    )
    record_secret_change(
        state,
        context,
        action="core.secrets.grant.create",
        detail=f"Created secret grant `{grant.grant_id}` for app `{grant.app_id}`.",
        payload={"grant_id": grant.grant_id, "app_id": grant.app_id, "secret_id": secret.secret_id, "secret_ref": grant.secret_ref},
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
        grant = _get_workspace_grant(state, grant_id=grant_id, workspace_id=context.workspace_id)
        return json_response(start_response, {"grant": grant_payload(grant, state=state)})
    if method == "POST" and action == "revoke":
        _get_workspace_grant(state, grant_id=grant_id, workspace_id=context.workspace_id)
        grant = revoke_app_secret_grant(state.secret_store, grant_id=grant_id)
        record_secret_change(
            state,
            context,
            action="core.secrets.grant.revoke",
            detail=f"Revoked secret grant `{grant.grant_id}`.",
            payload={"grant_id": grant.grant_id, "app_id": grant.app_id},
        )
        return json_response(start_response, {"grant": grant_payload(grant, state=state)})
    return json_response(start_response, {"error": "not_found"}, status="404 Not Found")


def _get_workspace_grant(state: PlatformState, *, grant_id: str, workspace_id: str) -> SecretGrantRecord:
    grant = state.secret_store.get_secret_grant(grant_id)
    if grant.workspace_id != workspace_id:
        raise SecretPolicyError("Secret grant cannot be managed outside its workspace.")
    return grant


def _handle_secret_audit(
    state: PlatformState,
    context: RequestSession,
    method: str,
    start_response: StartResponse,
) -> list[bytes]:
    if method != "GET":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    items = [
        audit_payload(item)
        for item in state.observability_store.list_audit(workspace_id=context.workspace_id)
        if item.action.startswith("core.secrets")
    ]
    return json_response(start_response, {"items": items})


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
