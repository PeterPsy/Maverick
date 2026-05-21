"""Validation helpers for Core Secrets grant mutations."""

from __future__ import annotations

from datetime import UTC, datetime

from core.api.platform_state import PlatformState
from core.api.secret_api_payloads import get_secret_for_ref
from core.apps.errors import AppHostingError, WorkspaceAppBindingNotFoundError
from core.apps.surfaces import resolve_workspace_app_surface
from core.secrets.errors import SecretPolicyError
from core.secrets.models import SecretRecord


APP_BACKEND_ACTION = "app.backend"


def get_active_secret_for_ref(state: PlatformState, *, secret_ref: str) -> SecretRecord:
    """Return the referenced secret only when it is active."""
    secret = get_secret_for_ref(state, secret_ref=secret_ref)
    if secret.status != "active":
        raise SecretPolicyError("Secret grants require an active secret.")
    return secret


def assert_enabled_workspace_app(state: PlatformState, *, workspace_id: str, app_id: str) -> None:
    """Require the target app to be installed and enabled in the workspace."""
    if not app_id:
        raise SecretPolicyError("Secret grants require an app id.")
    try:
        binding = state.app_store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    except WorkspaceAppBindingNotFoundError as exc:
        raise SecretPolicyError(f"Workspace app `{app_id}` is not installed in workspace `{workspace_id}`.") from exc
    if binding.status != "enabled":
        raise SecretPolicyError(f"Workspace app `{app_id}` is not enabled in workspace `{workspace_id}`.")
    try:
        resolve_workspace_app_surface(state.app_store, binding=binding, start_path=state.repository_root)
    except AppHostingError as exc:
        raise SecretPolicyError(f"Workspace app `{app_id}` is enabled but its surface is unavailable.") from exc


def assert_logical_name_available(state: PlatformState, *, workspace_id: str, app_id: str, logical_name: str) -> None:
    """Require one active grant per app logical name."""
    now = datetime.now(tz=UTC)
    for grant in state.secret_store.list_secret_grants(workspace_id=workspace_id, app_id=app_id, status="active"):
        if grant.expires_at is not None and grant.expires_at <= now:
            continue
        if grant.logical_name == logical_name:
            raise SecretPolicyError(f"Active secret grant `{logical_name}` already exists for app `{app_id}`.")


def assert_app_backend_logical_name_declared(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    logical_name: str,
    actions: list[str],
) -> None:
    """Require app.backend grants to target a contract-declared secret name."""
    normalized_actions = {str(action).strip().lower() for action in actions}
    if APP_BACKEND_ACTION not in normalized_actions:
        return
    binding = state.app_store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    try:
        _source_root, parsed = resolve_workspace_app_surface(state.app_store, binding=binding, start_path=state.repository_root)
    except AppHostingError as exc:
        raise SecretPolicyError(f"Workspace app `{app_id}` is enabled but its surface is unavailable.") from exc
    declared = {str(item).strip().lower() for item in parsed.contract.permissions.secrets.read}
    if logical_name not in declared:
        raise SecretPolicyError(
            f"App `{app_id}` does not declare secret logical name `{logical_name}` in permissions.secrets.read."
        )


def parse_expires_at(raw_value: object) -> datetime | None:
    """Parse an optional future ISO-8601 expiry timestamp."""
    value = str(raw_value or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else ""))
    except ValueError as exc:
        raise SecretPolicyError("Secret grant expiry must be an ISO-8601 datetime.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    parsed = parsed.astimezone(UTC)
    if parsed <= datetime.now(tz=UTC):
        raise SecretPolicyError("Secret grant expiry must be in the future.")
    return parsed
