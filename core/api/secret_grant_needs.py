"""Issue-oriented Core Secrets grant recommendations."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
import re

from core.api.platform_state import PlatformState
from core.api.secret_grant_targets import SecretConsumer, consumer_requires_secret, secret_grant_target_items
from core.secrets.app_delivery import APP_SECRET_ACTION, app_secret_grant_covers_targets, app_secret_target
from core.secrets.errors import SecretError
from core.secrets.models import SecretGrantRecord, SecretRecord
from core.secrets.secret_resolution import parse_secret_ref
from core.secrets.target_policy import target_allowed


APP_WRITE_GRANT_REASON = "Created automatically for app backend secret write delivery."


def secret_grant_need_items(
    state: PlatformState,
    *,
    workspace_id: str,
    start_path: Path,
) -> list[dict[str, object]]:
    """Return redaction-safe logical secret needs with recommended grant specs."""
    needs: list[dict[str, object]] = []
    grants = state.secret_store.list_secret_grants(workspace_id=workspace_id)
    secrets = state.secret_store.list_secrets()
    for target in secret_grant_target_items(state, workspace_id=workspace_id, start_path=start_path):
        app_id = str(target["app_id"])
        app_name = str(target["name"])
        consumers = target.get("consumers", {})
        if not isinstance(consumers, dict):
            continue
        for logical_name in sorted(consumers):
            consumer = consumers.get(logical_name)
            if not isinstance(consumer, dict) or not consumer_requires_secret(consumer):
                continue
            scopes = _need_scopes_for_consumer(
                consumer,
                grants=[
                    grant
                    for grant in grants
                    if grant.app_id == app_id and grant.logical_name == logical_name and _grant_has_resource_scope(grant)
                ],
            )
            for scope in scopes:
                needs.append(
                    _need_payload(
                        state,
                        workspace_id=workspace_id,
                        app_id=app_id,
                        app_name=app_name,
                        logical_name=logical_name,
                        consumer=consumer,
                        grants=[
                            grant
                            for grant in grants
                            if grant.app_id == app_id and grant.logical_name == logical_name and _grant_matches_scope(grant, scope)
                        ],
                        secrets=secrets,
                        scope=scope,
                    )
                )
    return needs


def _need_payload(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    app_name: str,
    logical_name: str,
    consumer: SecretConsumer,
    grants: list[SecretGrantRecord],
    secrets: list[SecretRecord],
    scope: dict[str, object],
) -> dict[str, object]:
    recommended_grant = _recommended_grant_spec(app_id=app_id, logical_name=logical_name, consumer=consumer, scope=scope)
    grant_state, selected_grant = _grant_state(state, grants=grants, recommended_grant=recommended_grant)
    credential_match = _credential_match(
        state,
        workspace_id=workspace_id,
        app_id=app_id,
        logical_name=logical_name,
        grants=grants,
        selected_grant=selected_grant,
        secrets=secrets,
        scope=scope,
    )
    value_state = _value_state(credential_match, grant_state=grant_state)
    app_managed = bool(consumer.get("app_managed") or credential_match.get("app_managed"))
    if app_managed and value_state == "active" and grant_state == "active":
        value_state = "managed_by_app_write"
    return {
        "app_id": app_id,
        "app_name": app_name,
        "logical_name": logical_name,
        "human_label": _human_label(logical_name),
        "scope": scope,
        "recommended_grant": recommended_grant,
        "value_state": value_state,
        "grant_state": grant_state,
        "user_action": _user_action(value_state=value_state, grant_state=grant_state, app_managed=app_managed),
        "credential_match": credential_match,
        "app_managed": app_managed,
    }


def _need_scopes_for_consumer(consumer: SecretConsumer, *, grants: list[SecretGrantRecord]) -> list[dict[str, object]]:
    if not bool(consumer.get("resource_scoped")):
        return [{"type": "workspace", "label": "Workspace"}]
    inventory_scopes = _consumer_resource_scopes(consumer)
    if inventory_scopes:
        return inventory_scopes
    concrete = sorted(
        {
            (str(grant.resource_type or "").strip().lower(), str(grant.resource_id or "").strip().lower())
            for grant in grants
            if grant.resource_type and grant.resource_id
        }
    )
    if concrete:
        return [
            {
                "type": "resource",
                "resource_type": resource_type,
                "resource_id": resource_id,
                "label": f"{_human_label(resource_type)} {resource_id}",
            }
            for resource_type, resource_id in concrete
        ]
    resource_types = _consumer_resource_types(consumer)
    return [
        {
            "type": "resource",
            "resource_type": resource_type,
            "resource_id": None,
            "label": _human_label(resource_type),
        }
        for resource_type in resource_types
    ]


def _consumer_resource_scopes(consumer: SecretConsumer) -> list[dict[str, object]]:
    raw_scopes = consumer.get("resource_scopes")
    if not isinstance(raw_scopes, list):
        return []
    scopes: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    allowed_types = set(_consumer_resource_types(consumer))
    for item in raw_scopes:
        if not isinstance(item, dict):
            continue
        resource_type = str(item.get("resource_type") or "").strip().lower()
        resource_id = str(item.get("resource_id") or "").strip().lower()
        if not resource_type or not resource_id or resource_type not in allowed_types:
            continue
        key = (resource_type, resource_id)
        if key in seen:
            continue
        seen.add(key)
        label = str(item.get("label") or "").strip() or f"{_human_label(resource_type)} {resource_id}"
        scopes.append(
            {
                "type": "resource",
                "resource_type": resource_type,
                "resource_id": resource_id,
                "label": label,
            }
        )
    return scopes


def _recommended_grant_spec(
    *,
    app_id: str,
    logical_name: str,
    consumer: SecretConsumer,
    scope: dict[str, object],
) -> dict[str, object]:
    target_patterns = _recommended_target_patterns(consumer, scope=scope)
    resource_type = scope.get("resource_type") if scope.get("type") == "resource" else None
    resource_id = scope.get("resource_id") if scope.get("type") == "resource" else None
    return {
        "actions": [APP_SECRET_ACTION],
        "target_patterns": target_patterns,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "reason": _recommended_reason(
            app_id=app_id,
            logical_name=logical_name,
            consumer=consumer,
            scope=scope,
            target_patterns=target_patterns,
        ),
    }


def _recommended_target_patterns(consumer: SecretConsumer, *, scope: dict[str, object]) -> list[str]:
    resource_type = str(scope.get("resource_type") or "").strip().lower() or None
    resource_id = str(scope.get("resource_id") or "").strip().lower() or None
    scoped = bool(resource_type and resource_id)
    targets: list[str] = []
    if consumer.get("backend"):
        targets.append(app_secret_target("backend", resource_type=resource_type, resource_id=resource_id) if scoped else app_secret_target("backend"))
    for command in _string_list(consumer.get("cli_commands")):
        surface = f"cli/{command}"
        targets.append(app_secret_target(surface, resource_type=resource_type, resource_id=resource_id) if scoped else app_secret_target(surface))
    for tool in _string_list(consumer.get("mcp_tools")):
        surface = f"mcp/{tool}"
        targets.append(app_secret_target(surface, resource_type=resource_type, resource_id=resource_id) if scoped else app_secret_target(surface))
    return _dedupe(targets) or ["maverick://app.backend/*"]


def _recommended_reason(
    *,
    app_id: str,
    logical_name: str,
    consumer: SecretConsumer,
    scope: dict[str, object],
    target_patterns: list[str],
) -> str:
    scope_text = "this resource" if scope.get("type") == "resource" and scope.get("resource_id") else "the workspace"
    if target_patterns == ["maverick://app.backend/*"]:
        return f"Allow {app_id} to use {logical_name} for all declared app backend consumers because no narrower target was available."
    surfaces = []
    if consumer.get("backend"):
        surfaces.append("backend")
    surfaces.extend(f"CLI `{item}`" for item in _string_list(consumer.get("cli_commands")))
    surfaces.extend(f"MCP `{item}`" for item in _string_list(consumer.get("mcp_tools")))
    surface_text = ", ".join(surfaces) or "declared consumers"
    return f"Allow {app_id} to use {logical_name} for {scope_text} through {surface_text}."


def _grant_state(
    state: PlatformState,
    *,
    grants: list[SecretGrantRecord],
    recommended_grant: dict[str, object],
) -> tuple[str, SecretGrantRecord | None]:
    if not grants:
        return "missing", None
    now = datetime.now(tz=UTC)
    ordered = sorted(grants, key=lambda item: item.updated_at, reverse=True)
    for grant in ordered:
        if grant.status == "active" and _grant_covers_recommendation(grant, recommended_grant) and _grant_is_current(grant, now=now):
            linked_status = _linked_secret_status(state, grant)
            if linked_status == "active":
                return "active", grant
            if linked_status == "missing":
                return "orphaned", grant
            return f"stale_secret_{linked_status}", grant
    for grant in ordered:
        if grant.status == "revoked":
            return "revoked", grant
        if grant.status == "active" and not _grant_is_current(grant, now=now):
            return "expired", grant
        if grant.status == "active" and not _grant_covers_recommendation(grant, recommended_grant):
            return "stale_target_mismatch", grant
    return "missing", None


def _credential_match(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    logical_name: str,
    grants: list[SecretGrantRecord],
    selected_grant: SecretGrantRecord | None,
    secrets: list[SecretRecord],
    scope: dict[str, object],
) -> dict[str, object]:
    candidates: list[dict[str, object]] = []
    grant_secret = _secret_from_grant(state, selected_grant) if selected_grant is not None else None
    if grant_secret is not None:
        candidates.append(_secret_candidate(grant_secret, method="grant_secret_ref", confidence="exact"))
    if grant_secret is None:
        for grant in sorted(grants, key=lambda item: item.updated_at, reverse=True):
            secret = _secret_from_grant(state, grant)
            if secret is not None:
                candidates.append(_secret_candidate(secret, method="grant_secret_ref", confidence="exact"))
                break
    if not candidates:
        exact_alias = _exact_alias_candidate(
            workspace_id=workspace_id,
            app_id=app_id,
            logical_name=logical_name,
            secrets=secrets,
            scope=scope,
        )
        if exact_alias is not None:
            candidates.append(_secret_candidate(exact_alias, method="exact_alias", confidence="high"))
    exact_label_candidates = _exact_label_candidates(logical_name=logical_name, secrets=secrets)
    if not candidates and exact_label_candidates:
        candidates.extend(
            _secret_candidate(secret, method="exact_label", confidence="review_required")
            for secret in exact_label_candidates
        )
    candidates = _dedupe_candidates(candidates)
    matched = bool(candidates and candidates[0]["confidence"] != "review_required")
    ambiguous = len(candidates) > 1 or bool(candidates and candidates[0]["confidence"] == "review_required")
    return {
        "matched": matched and not ambiguous,
        "method": str(candidates[0]["match_method"]) if candidates else "none",
        "confidence": str(candidates[0]["confidence"]) if candidates else "none",
        "ambiguous": ambiguous,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "app_managed": _is_app_managed(selected_grant, candidates),
    }


def _value_state(credential_match: dict[str, object], *, grant_state: str) -> str:
    candidates = credential_match.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return "orphaned" if grant_state == "orphaned" else "missing_or_unmatched"
    first = candidates[0]
    if not isinstance(first, dict):
        return "missing_or_unmatched"
    if credential_match.get("ambiguous"):
        return "candidate_needs_review"
    status = str(first.get("status") or "")
    if status == "active":
        return "active" if grant_state != "missing" else "available_ungranted"
    if status in {"disabled", "revoked"}:
        return status
    return "missing_or_unmatched"


def _user_action(*, value_state: str, grant_state: str, app_managed: bool) -> str:
    if app_managed and value_state == "managed_by_app_write" and grant_state == "active":
        return "none"
    if app_managed and value_state in {"missing_or_unmatched", "orphaned"}:
        return "complete_app_setup"
    if app_managed and value_state in {"disabled", "revoked"}:
        return "reconnect_app"
    if value_state in {"missing_or_unmatched", "orphaned"}:
        return "add_value"
    if value_state == "candidate_needs_review":
        return "review_value_match"
    if value_state in {"disabled", "revoked"}:
        return "rotate_or_replace_value"
    if grant_state == "active":
        return "none"
    if grant_state == "missing":
        return "create_grant"
    return "review_grant"


def _grant_covers_recommendation(grant: SecretGrantRecord, recommended_grant: dict[str, object]) -> bool:
    recommended_targets = _string_list(recommended_grant.get("target_patterns"))
    return app_secret_grant_covers_targets(grant, recommended_targets)


def _target_covered(target: str, patterns: list[str]) -> bool:
    try:
        return target_allowed(target, patterns)
    except SecretError:
        return target in patterns


def _grant_is_current(grant: SecretGrantRecord, *, now: datetime) -> bool:
    return grant.expires_at is None or grant.expires_at.astimezone(UTC) > now


def _linked_secret_status(state: PlatformState, grant: SecretGrantRecord) -> str:
    secret = _secret_from_grant(state, grant)
    return "missing" if secret is None else secret.status


def _secret_from_grant(state: PlatformState, grant: SecretGrantRecord | None) -> SecretRecord | None:
    if grant is None:
        return None
    try:
        parsed = parse_secret_ref(grant.secret_ref)
        if parsed.kind == "secret_id":
            return state.secret_store.get_secret(parsed.value)
        return state.secret_store.get_secret_by_alias(parsed.value)
    except SecretError:
        return None


def _exact_alias_candidate(
    *,
    workspace_id: str,
    app_id: str,
    logical_name: str,
    secrets: list[SecretRecord],
    scope: dict[str, object],
) -> SecretRecord | None:
    aliases = {logical_name}
    resource_type = str(scope.get("resource_type") or "").strip().lower()
    resource_id = str(scope.get("resource_id") or "").strip().lower()
    if resource_type and resource_id:
        aliases.add(_scoped_app_secret_alias(workspace_id, app_id, logical_name, resource_type, resource_id))
    for secret in secrets:
        if secret.alias and secret.alias.strip().lower() in aliases:
            return secret
    return None


def _exact_label_candidates(*, logical_name: str, secrets: list[SecretRecord]) -> list[SecretRecord]:
    normalized = _normalize_label(logical_name)
    return [secret for secret in secrets if _normalize_label(secret.label) == normalized]


def _secret_candidate(secret: SecretRecord, *, method: str, confidence: str) -> dict[str, object]:
    payload = asdict(secret)
    payload["match_method"] = method
    payload["confidence"] = confidence
    return payload


def _dedupe_candidates(candidates: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    deduped: list[dict[str, object]] = []
    for candidate in candidates:
        secret_id = str(candidate.get("secret_id") or "")
        if not secret_id or secret_id in seen:
            continue
        seen.add(secret_id)
        deduped.append(candidate)
    return deduped


def _is_app_managed(grant: SecretGrantRecord | None, candidates: list[dict[str, object]]) -> bool:
    if grant is not None and grant.reason == APP_WRITE_GRANT_REASON:
        return True
    if grant is None or not _grant_has_resource_scope(grant):
        return False
    return any(str(candidate.get("secret_id") or "").startswith("app-") for candidate in candidates)


def _grant_matches_scope(grant: SecretGrantRecord, scope: dict[str, object]) -> bool:
    if scope.get("type") == "workspace":
        return not _grant_has_resource_scope(grant)
    resource_type = str(scope.get("resource_type") or "").strip().lower()
    resource_id = str(scope.get("resource_id") or "").strip().lower()
    if not resource_id:
        return False
    return str(grant.resource_type or "").strip().lower() == resource_type and str(grant.resource_id or "").strip().lower() == resource_id


def _grant_has_resource_scope(grant: SecretGrantRecord) -> bool:
    return bool(grant.resource_type and grant.resource_id)


def _consumer_resource_types(consumer: SecretConsumer) -> list[str]:
    values = consumer.get("resource_types")
    if not isinstance(values, list):
        return []
    return sorted({str(item).strip().lower() for item in values if str(item).strip()})


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped


def _human_label(value: str) -> str:
    return str(value).replace("_", "-").replace("-", " ").strip().title()


def _normalize_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).strip().lower()).strip()


def _secret_segment(value: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower()).strip("-") or "item"


def _scoped_app_secret_alias(
    workspace_id: str,
    app_id: str,
    logical_name: str,
    resource_type: str,
    resource_id: str,
) -> str:
    return "-".join(_secret_segment(item) for item in [workspace_id, app_id, logical_name, resource_type, resource_id])
