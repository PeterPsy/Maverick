"""Audit/event helpers for Core Secrets lifecycle side effects."""

from __future__ import annotations

from core.observability.service import record_platform_audit, record_platform_event
from core.secrets.models import SecretGrantRecord


def record_cascaded_grant_revocation_audit(
    observability_store,
    *,
    secret_id: str,
    grants: list[SecretGrantRecord],
    actor_user_id: str | None,
    source_workspace_id: str | None,
    actor_agent_id: str | None = None,
    runtime_session_id: str | None = None,
) -> None:
    """Record one cascade revoke audit/event in each impacted grant workspace."""
    if observability_store is None:
        return
    for grant in grants:
        payload = {
            "actor_user_id": actor_user_id,
            "secret_id": secret_id,
            "grant_id": grant.grant_id,
            "app_id": grant.app_id,
            "actor_agent_id": actor_agent_id,
            "runtime_session_id": runtime_session_id,
            "source_workspace_id": source_workspace_id,
        }
        record_platform_audit(
            observability_store,
            action="core.secrets.grant.revoke.cascade",
            status="succeeded",
            source_domain="secrets",
            detail=f"Revoked secret grant `{grant.grant_id}` because linked secret `{secret_id}` changed state.",
            workspace_id=grant.workspace_id,
            app_id=grant.app_id,
            runtime_session_id=runtime_session_id,
            payload=payload,
        )
        record_platform_event(
            observability_store,
            event_type="core.secrets.grant.revoke.cascade",
            event_plane="runtime" if runtime_session_id else "platform",
            source_domain="secrets",
            workspace_id=grant.workspace_id,
            app_id=grant.app_id,
            runtime_session_id=runtime_session_id,
            payload=payload,
        )
