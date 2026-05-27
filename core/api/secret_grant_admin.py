"""Shared Core Secrets grant admin actions for HTTP, CLI, and MCP."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from core.api.secret_api_payloads import audit_payload, grant_payload
from core.api.secret_grant_needs import secret_grant_need_items
from core.api.secret_grant_targets import (
    assert_app_backend_resource_scope_allowed,
    assert_app_backend_targets_match_consumers,
    secret_grant_target_items,
)
from core.api.secret_grant_validation import (
    assert_app_backend_logical_name_declared,
    assert_enabled_workspace_app,
    assert_logical_name_target_available,
    get_active_secret_for_ref,
    parse_expires_at,
)
from core.apps.store import AppStore
from core.observability.store import ObservabilityStore
from core.secrets.app_delivery import assert_app_backend_targets_deliverable
from core.secrets.errors import SecretPolicyError
from core.secrets.models import SecretGrantRecord, SecretRecord
from core.secrets.service import build_secret_ref, grant_app_secret_use, revoke_app_secret_grant
from core.secrets.store import SecretStore


class SecretGrantAdminState(Protocol):
    """Store bundle required by Core Secrets grant admin helpers."""

    repository_root: Path
    app_store: AppStore
    secret_store: SecretStore
    observability_store: ObservabilityStore | None


def list_grant_payloads(
    state: SecretGrantAdminState,
    *,
    workspace_id: str,
) -> list[dict[str, object]]:
    """Return redaction-safe grant payloads for one workspace."""
    return [
        grant_payload(item, state=state)
        for item in state.secret_store.list_secret_grants(workspace_id=workspace_id)
    ]


def create_secret_grant_from_payload(
    state: SecretGrantAdminState,
    *,
    workspace_id: str,
    payload: dict[str, Any],
    created_by_user_id: str | None,
) -> tuple[SecretGrantRecord, SecretRecord]:
    """Validate and create one app secret grant from an admin payload."""
    secret_ref = str(payload.get("secret_ref") or "").strip()
    if not secret_ref:
        secret_id = str(payload.get("secret_id") or "").strip() or None
        alias = str(payload.get("alias") or "").strip() or None
        secret_ref = build_secret_ref(secret_id=secret_id, alias=alias)
    secret = get_active_secret_for_ref(state, secret_ref=secret_ref)
    app_id = str(payload.get("app_id") or "").strip()
    logical_name = str(payload.get("logical_name") or "").strip().lower()
    actions = [str(item) for item in payload.get("actions", [])] if isinstance(payload.get("actions"), list) else []
    target_patterns = (
        [str(item) for item in payload.get("target_patterns", [])]
        if isinstance(payload.get("target_patterns"), list)
        else None
    )
    assert_enabled_workspace_app(state, workspace_id=workspace_id, app_id=app_id)
    assert_app_backend_logical_name_declared(
        state,
        workspace_id=workspace_id,
        app_id=app_id,
        logical_name=logical_name,
        actions=actions,
    )
    assert_app_backend_targets_deliverable(actions, target_patterns)
    resource_type = str(payload.get("resource_type") or "").strip() or None
    resource_id = str(payload.get("resource_id") or "").strip() or None
    assert_app_backend_targets_match_consumers(
        state,
        workspace_id=workspace_id,
        app_id=app_id,
        logical_name=logical_name,
        actions=actions,
        target_patterns=target_patterns,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    assert_app_backend_resource_scope_allowed(
        state,
        workspace_id=workspace_id,
        app_id=app_id,
        logical_name=logical_name,
        actions=actions,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    assert_logical_name_target_available(
        state,
        workspace_id=workspace_id,
        app_id=app_id,
        logical_name=logical_name,
        actions=actions,
        target_patterns=target_patterns,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    grant = grant_app_secret_use(
        state.secret_store,
        workspace_id=workspace_id,
        app_id=app_id,
        logical_name=logical_name,
        secret_ref=secret_ref,
        actions=actions,
        target_patterns=target_patterns,
        expires_at=parse_expires_at(payload.get("expires_at")),
        created_by_user_id=created_by_user_id,
        reason=str(payload.get("reason") or "").strip() or None,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    return grant, secret


def revoke_workspace_secret_grant(
    state: SecretGrantAdminState,
    *,
    workspace_id: str,
    grant_id: str,
) -> SecretGrantRecord:
    """Validate workspace ownership and revoke one secret grant."""
    get_workspace_secret_grant(state, workspace_id=workspace_id, grant_id=grant_id)
    return revoke_app_secret_grant(state.secret_store, grant_id=grant_id)


def get_workspace_secret_grant(
    state: SecretGrantAdminState,
    *,
    workspace_id: str,
    grant_id: str,
) -> SecretGrantRecord:
    """Return a grant only when it belongs to the requested workspace."""
    grant = state.secret_store.get_secret_grant(grant_id)
    if grant.workspace_id != workspace_id:
        raise SecretPolicyError("Secret grant cannot be managed outside its workspace.")
    return grant


def list_secret_grant_targets(
    state: SecretGrantAdminState,
    *,
    workspace_id: str,
) -> dict[str, object]:
    """Return redaction-safe grant target inventory plus recommended needs."""
    return {
        "items": secret_grant_target_items(state, workspace_id=workspace_id, start_path=state.repository_root),
        "needs": secret_grant_need_items(state, workspace_id=workspace_id, start_path=state.repository_root),
    }


def list_secret_grant_recommendations(
    state: SecretGrantAdminState,
    *,
    workspace_id: str,
) -> list[dict[str, object]]:
    """Return redaction-safe recommended grant specs and issue state."""
    return secret_grant_need_items(state, workspace_id=workspace_id, start_path=state.repository_root)


def list_secret_audit_payloads(
    state: SecretGrantAdminState,
    *,
    workspace_id: str,
) -> list[dict[str, object]]:
    """Return redaction-safe Core Secrets audit records for one workspace."""
    if state.observability_store is None:
        return []
    return [
        audit_payload(item)
        for item in state.observability_store.list_audit(workspace_id=workspace_id)
        if item.action.startswith("core.secrets")
    ]
