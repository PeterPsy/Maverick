"""HTTP API for platform-owned secret management."""

from __future__ import annotations

import logging
from pathlib import Path

from core.apps.errors import AppHostingError
from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.apps.surface_descriptors import app_cli_command_required_secrets, app_mcp_tool_required_secrets
from core.api.http import StartResponse, json_response, read_json_body
from core.api.platform_state import PlatformState
from core.api.secret_audit_records import record_cascaded_grant_revocations, record_secret_change
from core.api.secret_api_payloads import audit_payload, grant_payload, secret_payload
from core.api.secret_grant_validation import (
    APP_BACKEND_ACTION,
    assert_app_backend_logical_name_declared,
    assert_enabled_workspace_app,
    assert_logical_name_target_available,
    get_active_secret_for_ref,
    parse_expires_at,
)
from core.api.session_api import RequestSession, require_session
from core.secrets.app_delivery import app_secret_target, assert_app_backend_targets_deliverable
from core.secrets.errors import SecretError, SecretPolicyError
from core.secrets.models import SecretGrantRecord
from core.secrets.service import (
    build_secret_ref,
    create_platform_secret,
    disable_platform_secret_with_revocations,
    grant_app_secret_use,
    resolve_app_secret_grant,
    revoke_app_secret_grant,
    revoke_platform_secret_with_revocations,
    rotate_platform_secret,
)
from core.secrets.target_policy import normalize_target_patterns_or_wildcard, target_allowed


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
        declared_logical_names = sorted(
            {str(item).strip().lower() for item in parsed.contract.permissions.secrets.read if str(item).strip()}
        )
        consumers = _secret_consumers_by_logical_name(
            source_root=_source_root,
            declared_logical_names=declared_logical_names,
            backend_declared=parsed.contract.entrypoints.backend is not None,
            cli_commands=[str(item).strip() for item in parsed.contract.capabilities.cli_commands if str(item).strip()],
            mcp_tools=[str(item).strip() for item in parsed.contract.capabilities.mcp_tools if str(item).strip()],
        )
        logical_names = sorted(
            logical_name for logical_name, consumer in consumers.items() if _consumer_requires_secret(consumer)
        )
        if not logical_names:
            continue
        consumer_cli_commands = sorted(
            {command for logical_name in logical_names for command in consumers[logical_name]["cli_commands"]}
        )
        consumer_mcp_tools = sorted(
            {tool for logical_name in logical_names for tool in consumers[logical_name]["mcp_tools"]}
        )
        items.append(
            {
                "app_id": binding.app_id,
                "public_app_id": binding.public_app_id or parsed.app_id,
                "mount_app_id": binding.mount_app_id or binding.app_id,
                "name": parsed.name,
                "status": binding.status,
                "logical_names": logical_names,
                "consumers": {logical_name: consumers[logical_name] for logical_name in logical_names},
                "surfaces": {
                    "backend": any(consumers[logical_name]["backend"] for logical_name in logical_names),
                    "cli_commands": consumer_cli_commands,
                    "mcp_tools": consumer_mcp_tools,
                },
            }
        )
    return json_response(start_response, {"items": items})


def _secret_consumers_by_logical_name(
    *,
    source_root: Path,
    declared_logical_names: list[str],
    backend_declared: bool,
    cli_commands: list[str],
    mcp_tools: list[str],
) -> dict[str, dict[str, object]]:
    consumers: dict[str, dict[str, object]] = {
        logical_name: {"backend": backend_declared, "cli_commands": [], "mcp_tools": []}
        for logical_name in declared_logical_names
    }
    for command in cli_commands:
        for logical_name in app_cli_command_required_secrets(
            source_root,
            command,
            declared_secret_names=declared_logical_names,
        ):
            consumers.setdefault(logical_name, {"backend": False, "cli_commands": [], "mcp_tools": []})
            cli_consumers = consumers[logical_name]["cli_commands"]
            if isinstance(cli_consumers, list) and command not in cli_consumers:
                cli_consumers.append(command)
    for tool in mcp_tools:
        for logical_name in app_mcp_tool_required_secrets(
            source_root,
            tool,
            declared_secret_names=declared_logical_names,
        ):
            consumers.setdefault(logical_name, {"backend": False, "cli_commands": [], "mcp_tools": []})
            mcp_consumers = consumers[logical_name]["mcp_tools"]
            if isinstance(mcp_consumers, list) and tool not in mcp_consumers:
                mcp_consumers.append(tool)
    return consumers


def _consumer_requires_secret(consumer: dict[str, object]) -> bool:
    return bool(consumer.get("backend") or consumer.get("cli_commands") or consumer.get("mcp_tools"))


def _assert_app_backend_targets_match_consumers(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    logical_name: str,
    actions: list[str],
    target_patterns: list[str] | None,
) -> None:
    normalized_actions = {str(action).strip().lower() for action in actions}
    if APP_BACKEND_ACTION not in normalized_actions:
        return
    binding = state.app_store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    try:
        source_root, parsed = resolve_workspace_app_surface(state.app_store, binding=binding, start_path=state.repository_root)
    except AppHostingError as exc:
        raise SecretPolicyError(f"Workspace app `{app_id}` is enabled but its surface is unavailable.") from exc
    declared_logical_names = sorted(
        {str(item).strip().lower() for item in parsed.contract.permissions.secrets.read if str(item).strip()}
    )
    consumers = _secret_consumers_by_logical_name(
        source_root=source_root,
        declared_logical_names=declared_logical_names,
        backend_declared=parsed.contract.entrypoints.backend is not None,
        cli_commands=[str(item).strip() for item in parsed.contract.capabilities.cli_commands if str(item).strip()],
        mcp_tools=[str(item).strip() for item in parsed.contract.capabilities.mcp_tools if str(item).strip()],
    ).get(logical_name)
    consumer_targets = _consumer_targets(consumers)
    if not consumer_targets:
        raise SecretPolicyError(f"App `{app_id}` has no declared consumers for secret logical name `{logical_name}`.")
    for pattern in normalize_target_patterns_or_wildcard(target_patterns):
        if pattern in {"*", "maverick://app.backend/*"}:
            continue
        if not any(_target_overlaps(pattern, consumer_target) for consumer_target in consumer_targets):
            raise SecretPolicyError(
                f"App `{app_id}` does not declare a secret consumer matching target `{pattern}` for `{logical_name}`."
            )


def _consumer_targets(consumer: dict[str, object] | None) -> list[str]:
    if not consumer:
        return []
    targets: list[str] = []
    if consumer.get("backend"):
        targets.append(app_secret_target("backend"))
    for command in consumer.get("cli_commands", []):
        targets.append(app_secret_target(f"cli/{command}"))
    for tool in consumer.get("mcp_tools", []):
        targets.append(app_secret_target(f"mcp/{tool}"))
    return targets


def _target_overlaps(pattern: str, target: str) -> bool:
    if pattern == "*" or target == "*" or pattern == target:
        return True
    try:
        return target_allowed(target, [pattern]) or target_allowed(pattern, [target])
    except SecretError:
        return pattern == target


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
    assert_app_backend_logical_name_declared(
        state,
        workspace_id=context.workspace_id,
        app_id=app_id,
        logical_name=logical_name,
        actions=actions,
    )
    assert_app_backend_targets_deliverable(actions, target_patterns)
    _assert_app_backend_targets_match_consumers(
        state,
        workspace_id=context.workspace_id,
        app_id=app_id,
        logical_name=logical_name,
        actions=actions,
        target_patterns=target_patterns,
    )
    assert_logical_name_target_available(
        state,
        workspace_id=context.workspace_id,
        app_id=app_id,
        logical_name=logical_name,
        actions=actions,
        target_patterns=target_patterns,
    )
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
