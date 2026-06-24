"""Grant-based app secret delivery helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from core.observability.service import record_platform_audit, record_platform_event
from core.secrets.errors import SecretError, SecretPolicyError
from core.secrets.models import SecretGrantRecord
from core.secrets.service import resolve_app_secret_grant
from core.secrets.store import SecretStore
from core.secrets.target_policy import (
    normalize_target_patterns_or_wildcard,
    sanitize_request_context_for_audit,
    target_allowed,
)


APP_SECRET_ACTION = "app.backend"
LEGACY_APP_SECRET_ACTION = "app.secret.read"
APP_SECRET_TARGET_PREFIX = "maverick://app.backend"


@dataclass(frozen=True)
class AppSecretPayloadResult:
    """Resolved app secret payload plus non-sensitive delivery metadata."""

    secrets: dict[str, str]
    errors: list[dict[str, str]]


@dataclass(frozen=True)
class AppSecretRequest:
    """One logical secret delivery request for a specific resource scope."""

    logical_names: list[str]
    resource_type: str | None = None
    resource_id: str | None = None


def app_secret_target(surface: str, *, resource_type: str | None = None, resource_id: str | None = None) -> str:
    """Return the synthetic target used for app entrypoint secret delivery."""
    normalized = str(surface or "entrypoint").strip().lower().replace("_", "-") or "entrypoint"
    target = f"{APP_SECRET_TARGET_PREFIX}/{normalized}"
    normalized_resource_type = str(resource_type or "").strip().lower().replace("_", "-")
    normalized_resource_id = str(resource_id or "").strip().lower().replace("_", "-")
    if normalized_resource_type and normalized_resource_id:
        target = f"{target}/{normalized_resource_type}/{normalized_resource_id}"
    return target


def assert_app_backend_targets_deliverable(actions: list[str], target_patterns: list[str] | None) -> None:
    """Reject app.backend grants whose target patterns cannot match app delivery."""
    normalized_actions = {str(action).strip().lower() for action in actions}
    if APP_SECRET_ACTION not in normalized_actions:
        return
    normalized_targets = normalize_target_patterns_or_wildcard(target_patterns)
    if "*" in normalized_targets and len(normalized_actions) > 1:
        raise SecretPolicyError("`*` targets are not allowed on grants that mix `app.backend` with other actions.")
    if any(target == "*" or target.startswith(f"{APP_SECRET_TARGET_PREFIX}/") for target in normalized_targets):
        return
    raise SecretPolicyError("`app.backend` grants must allow `*` or `maverick://app.backend/*` targets.")


def resolve_app_secret_payload(
    secret_store: SecretStore | None,
    *,
    workspace_id: str,
    app_id: str,
    allowed_logical_names: list[str] | None,
    surface: str,
    runtime_session_id: str | None = None,
    actor_user_id: str | None = None,
    observability_store=None,
    request_context: dict[str, str] | None = None,
    fail_closed: bool = True,
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> AppSecretPayloadResult:
    """Resolve grant-authorized app secrets for backend, CLI, and MCP payloads."""
    if secret_store is None:
        return AppSecretPayloadResult(secrets={}, errors=[])
    allowed = _declared_logical_names(allowed_logical_names)
    if not allowed:
        return AppSecretPayloadResult(secrets={}, errors=[])
    secrets: dict[str, str] = {}
    errors: list[dict[str, str]] = []
    target = app_secret_target(surface, resource_type=resource_type, resource_id=resource_id)
    base_target = app_secret_target(surface)
    requested_resource_type, requested_resource_id = _normalize_request_resource(resource_type, resource_id)
    now = datetime.now(tz=UTC)
    grants_by_logical_name: dict[str, list[SecretGrantRecord]] = {logical_name: [] for logical_name in allowed}
    for grant in secret_store.list_secret_grants(workspace_id=workspace_id, app_id=app_id, status="active"):
        if (
            grant.logical_name in grants_by_logical_name
            and _grant_resource_matches(
                grant,
                requested_resource_type=requested_resource_type,
                requested_resource_id=requested_resource_id,
            )
            and _grant_delivery_target(grant, target=target, base_target=base_target, now=now)
        ):
            grants_by_logical_name[grant.logical_name].append(grant)
    for logical_name in allowed:
        candidates = sorted(grants_by_logical_name[logical_name], key=lambda item: item.created_at, reverse=True)
        if not candidates:
            errors.append({"logical_name": logical_name, "grant_id": "", "error": "SecretGrantMissing"})
            _record_delivery_denial(
                observability_store,
                workspace_id=workspace_id,
                app_id=app_id,
                logical_name=logical_name,
                surface=surface,
                target=target,
                runtime_session_id=runtime_session_id,
                actor_user_id=actor_user_id,
                request_context=request_context,
            )
            if fail_closed:
                raise SecretPolicyError(f"App `{app_id}` declared secret `{logical_name}` but has no active grant.")
            continue
        grant = candidates[0]
        try:
            grant_target = _grant_delivery_target(grant, target=target, base_target=base_target, now=now) or target
            grant_action = app_secret_delivery_action_for_grant(grant) or APP_SECRET_ACTION
            lease = resolve_app_secret_grant(
                secret_store,
                workspace_id=workspace_id,
                app_id=app_id,
                grant_id=grant.grant_id,
                action=grant_action,
                target=grant_target,
                runtime_session_id=runtime_session_id,
                actor_user_id=actor_user_id,
                observability_store=observability_store,
                request_context=request_context,
            )
        except SecretError as error:
            errors.append({"logical_name": logical_name, "grant_id": grant.grant_id, "error": error.__class__.__name__})
            if fail_closed:
                raise SecretPolicyError(
                    f"App secret grant `{grant.grant_id}` for `{app_id}.{logical_name}` was denied."
                ) from error
            continue
        secrets[logical_name] = lease.value
    return AppSecretPayloadResult(secrets=secrets, errors=errors)


def resolve_app_secret_payload_requests(
    secret_store: SecretStore | None,
    *,
    workspace_id: str,
    app_id: str,
    requests: list[AppSecretRequest],
    surface: str,
    runtime_session_id: str | None = None,
    actor_user_id: str | None = None,
    observability_store=None,
    request_context: dict[str, str] | None = None,
    fail_closed: bool = True,
) -> AppSecretPayloadResult:
    """Resolve one or more app secret requests and merge the delivered payload."""
    secrets: dict[str, str] = {}
    errors: list[dict[str, str]] = []
    for request in requests:
        result = resolve_app_secret_payload(
            secret_store,
            workspace_id=workspace_id,
            app_id=app_id,
            allowed_logical_names=request.logical_names,
            surface=surface,
            runtime_session_id=runtime_session_id,
            actor_user_id=actor_user_id,
            observability_store=observability_store,
            request_context=request_context,
            fail_closed=fail_closed,
            resource_type=request.resource_type,
            resource_id=request.resource_id,
        )
        secrets.update(result.secrets)
        errors.extend(result.errors)
    return AppSecretPayloadResult(secrets=secrets, errors=errors)


def _declared_logical_names(values: list[str] | None) -> list[str]:
    logical_names: list[str] = []
    for value in values or []:
        logical_name = str(value).strip().lower()
        if logical_name and logical_name not in logical_names:
            logical_names.append(logical_name)
    return logical_names


def _normalize_request_resource(resource_type: str | None, resource_id: str | None) -> tuple[str | None, str | None]:
    normalized_resource_type = str(resource_type or "").strip().lower() or None
    normalized_resource_id = str(resource_id or "").strip().lower() or None
    if not normalized_resource_type or not normalized_resource_id:
        return None, None
    return normalized_resource_type, normalized_resource_id


def _grant_resource_matches(
    grant: SecretGrantRecord,
    *,
    requested_resource_type: str | None,
    requested_resource_id: str | None,
) -> bool:
    grant_resource_type = str(grant.resource_type or "").strip().lower() or None
    grant_resource_id = str(grant.resource_id or "").strip().lower() or None
    grant_is_resource_scoped = bool(grant_resource_type and grant_resource_id)
    request_is_resource_scoped = bool(requested_resource_type and requested_resource_id)
    if grant_is_resource_scoped != request_is_resource_scoped:
        return False
    if not grant_is_resource_scoped:
        return True
    return grant_resource_type == requested_resource_type and grant_resource_id == requested_resource_id


def _grant_is_current(grant: SecretGrantRecord, *, now: datetime) -> bool:
    return grant.expires_at is None or grant.expires_at.astimezone(UTC) > now


def _grant_deliverable(grant: SecretGrantRecord, *, target: str, now: datetime) -> bool:
    if not _grant_is_current(grant, now=now):
        return False
    if app_secret_delivery_action_for_grant(grant) is None:
        return False
    try:
        return target_allowed(target, grant.target_patterns)
    except SecretError:
        return False


def _grant_delivery_target(grant: SecretGrantRecord, *, target: str, base_target: str, now: datetime) -> str | None:
    if _grant_deliverable(grant, target=target, now=now):
        return target
    if target != base_target and _grant_deliverable(grant, target=base_target, now=now):
        return base_target
    return None


def app_secret_delivery_action_for_grant(grant: SecretGrantRecord) -> str | None:
    """Return the grant action that can authorize app backend delivery."""
    actions = {str(action).strip().lower() for action in grant.actions}
    if APP_SECRET_ACTION in actions:
        return APP_SECRET_ACTION
    if LEGACY_APP_SECRET_ACTION in actions and _has_app_backend_target_pattern(grant.target_patterns):
        return LEGACY_APP_SECRET_ACTION
    return None


def app_secret_grant_covers_targets(grant: SecretGrantRecord, targets: list[str]) -> bool:
    """Return whether one current or legacy app grant covers all app backend targets."""
    if app_secret_delivery_action_for_grant(grant) is None:
        return False
    return all(_target_covered_by_grant(target, grant.target_patterns) for target in targets)


def _has_app_backend_target_pattern(target_patterns: list[str]) -> bool:
    normalized_targets = normalize_target_patterns_or_wildcard(target_patterns)
    return any(
        target != "*" and (target == APP_SECRET_TARGET_PREFIX or target.startswith(f"{APP_SECRET_TARGET_PREFIX}/"))
        for target in normalized_targets
    )


def _target_covered_by_grant(target: str, patterns: list[str]) -> bool:
    try:
        return target_allowed(target, patterns)
    except SecretError:
        return target in patterns


def _record_delivery_denial(
    observability_store,
    *,
    workspace_id: str,
    app_id: str,
    logical_name: str,
    surface: str,
    target: str,
    runtime_session_id: str | None,
    actor_user_id: str | None,
    request_context: dict[str, str] | None,
) -> None:
    if observability_store is None:
        return
    payload = {
        "app_id": app_id,
        "logical_name": logical_name,
        "surface": surface,
        "target": target,
        "actor_user_id": actor_user_id,
        "request_context": sanitize_request_context_for_audit(request_context),
        "error_code": "grant_missing",
    }
    record_platform_audit(
        observability_store,
        action="core.secrets.delivery",
        status="failed",
        source_domain="secrets",
        detail=f"App `{app_id}` declared secret `{logical_name}` but no current delivery grant was available.",
        workspace_id=workspace_id,
        app_id=app_id,
        runtime_session_id=runtime_session_id,
        payload=payload,
    )
    record_platform_event(
        observability_store,
        event_type="core.secrets.delivery",
        event_plane="runtime" if runtime_session_id else "platform",
        source_domain="secrets",
        workspace_id=workspace_id,
        app_id=app_id,
        runtime_session_id=runtime_session_id,
        payload=payload,
    )
