"""Audit/event recording helpers for Core Secrets API mutations."""

from __future__ import annotations

from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession
from core.observability.service import record_platform_audit, record_platform_event
from core.secrets.audit import record_cascaded_grant_revocation_audit
from core.secrets.models import SecretGrantRecord


def record_secret_change(
    state: PlatformState,
    context: RequestSession,
    *,
    action: str,
    detail: str,
    payload: dict[str, object],
) -> None:
    """Record one admin-visible secret-domain mutation."""
    event_payload = {"actor_user_id": context.user.user_id, **payload}
    record_platform_audit(
        state.observability_store,
        action=action,
        status="succeeded",
        source_domain="secrets",
        detail=detail,
        workspace_id=context.workspace_id,
        payload=event_payload,
    )
    record_platform_event(
        state.observability_store,
        event_type=action,
        event_plane="platform",
        source_domain="secrets",
        workspace_id=context.workspace_id,
        payload=event_payload,
    )


def record_cascaded_grant_revocations(
    state: PlatformState,
    context: RequestSession,
    *,
    secret_id: str,
    grants: list[SecretGrantRecord],
) -> None:
    """Record one cascade revoke audit/event in each impacted grant workspace."""
    record_cascaded_grant_revocation_audit(
        state.observability_store,
        secret_id=secret_id,
        grants=grants,
        actor_user_id=context.user.user_id,
        source_workspace_id=context.workspace_id,
    )
