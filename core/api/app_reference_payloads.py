"""Payload normalization for app-owned references."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.api.app_reference_providers import (
    call_reference_tool,
    mcp_context_for_request,
    public_provider_payload,
    reference_providers,
    visible_workspace_apps,
)
from core.api.session_api import RequestSession
from core.mcp.models import McpInvocationContext

logger = logging.getLogger(__name__)


def manifest_provider_payload(
    state,
    provider: dict[str, Any],
    *,
    context: McpInvocationContext,
    start_path: Path,
) -> dict[str, Any]:
    payload = public_provider_payload(provider)
    if not provider["tools"].get("manifest"):
        return payload
    result = call_reference_tool(
        state,
        provider,
        "manifest",
        context=context,
        arguments={},
        start_path=start_path,
    )
    payload["entity_types"] = normalize_manifest_entities(result, provider=provider)
    return payload


def normalize_manifest_entities(result: object, *, provider: dict[str, Any]) -> list[dict[str, Any]]:
    declared_by_type = {
        str(entity.get("entity_type") or ""): entity
        for entity in provider["entities"]
        if str(entity.get("entity_type") or "")
    }
    raw_entities: object = None
    if isinstance(result, dict):
        raw_entities = result.get("entity_types") or result.get("entities")
    if not isinstance(raw_entities, list):
        raw_entities = provider["entities"]

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_entities:
        if not isinstance(raw, dict):
            continue
        entity_type = _bounded_text(raw.get("entity_type") or raw.get("type"), max_length=120)
        declaration = declared_by_type.get(entity_type)
        if declaration is None or entity_type in seen:
            continue
        seen.add(entity_type)
        normalized.append(
            {
                "entity_type": entity_type,
                "display_name": _bounded_text(
                    raw.get("display_name") or raw.get("name") or declaration.get("display_name") or entity_type,
                    max_length=120,
                ),
                "searchable": _declared_manifest_bool(raw, declaration, "searchable"),
                "resolvable": _declared_manifest_bool(raw, declaration, "resolvable"),
                "summarizable": _declared_manifest_bool(raw, declaration, "summarizable"),
                "deep_link_supported": _declared_manifest_bool(raw, declaration, "deep_link_supported"),
            }
        )
    return normalized


def normalize_reference_item(
    raw_item: object,
    *,
    provider: dict[str, Any],
    fallback_entity_type: str,
) -> dict[str, Any] | None:
    if not isinstance(raw_item, dict):
        return None
    entity_type = _bounded_text(raw_item.get("entity_type") or fallback_entity_type, max_length=120)
    entity_id = _bounded_text(raw_item.get("entity_id") or raw_item.get("id"), max_length=240)
    if not entity_type or not entity_id:
        return None
    declared_entity_types = {
        str(entity.get("entity_type") or "")
        for entity in provider["entities"]
        if str(entity.get("entity_type") or "")
    }
    if entity_type != fallback_entity_type or entity_type not in declared_entity_types:
        return None
    label = _bounded_text(raw_item.get("label") or raw_item.get("title") or entity_id, max_length=240)
    summary = _bounded_text(raw_item.get("summary") or raw_item.get("subtitle"), max_length=1000)
    item: dict[str, Any] = {
        "type": "entity",
        "app_id": provider["app_id"],
        "entity_type": entity_type,
        "entity_id": entity_id,
        "label": label,
        "summary": summary,
    }
    deep_link = _deep_link(provider, raw_item)
    if deep_link:
        item["deep_link"] = deep_link
    if "exists" in raw_item:
        item["exists"] = bool(raw_item.get("exists"))
    metadata = raw_item.get("metadata")
    if isinstance(metadata, dict):
        item["metadata"] = metadata
    return item


def materialize_runtime_app_references(
    state,
    *,
    context: RequestSession,
    references: list[dict[str, object]],
    start_path: Path,
) -> list[dict[str, object]]:
    """Verify client-submitted references and enrich entities from owning apps."""
    visible_apps = visible_workspace_apps(state, context=context, start_path=start_path)
    providers_by_app_id = {
        provider["app_id"]: provider
        for provider in reference_providers(state, context=context, start_path=start_path)
    }
    mcp_context = mcp_context_for_request(state, context)
    materialized: list[dict[str, object]] = []
    seen: set[str] = set()
    for reference in references:
        app_id = _bounded_text(reference.get("app_id"), max_length=120)
        if not app_id:
            continue
        if str(reference.get("type") or "app").strip().lower() == "entity":
            payload = _materialize_runtime_entity_reference(
                state,
                provider=providers_by_app_id.get(app_id),
                reference=reference,
                context=mcp_context,
                start_path=start_path,
            )
        else:
            app = visible_apps.get(app_id)
            payload = (
                {
                    "type": "app",
                    "app_id": app_id,
                    "label": _bounded_text(app.get("name"), max_length=240),
                }
                if app is not None
                else None
            )
        if payload is None:
            continue
        key = _reference_key(payload)
        if key in seen:
            continue
        seen.add(key)
        materialized.append(payload)
    return materialized


def _materialize_runtime_entity_reference(
    state,
    *,
    provider: dict[str, Any] | None,
    reference: dict[str, object],
    context: McpInvocationContext,
    start_path: Path,
) -> dict[str, object] | None:
    if provider is None:
        return None
    entity_type = _bounded_text(reference.get("entity_type"), max_length=120)
    entity_id = _bounded_text(reference.get("entity_id") or reference.get("id"), max_length=240)
    if not entity_type or not entity_id:
        return None
    declaration = next((item for item in provider["entities"] if item.get("entity_type") == entity_type), None)
    if declaration is None:
        return None

    resolved = None
    if declaration.get("resolvable") and provider["tools"].get("resolve"):
        resolved = _call_runtime_reference_lookup(
            state,
            provider=provider,
            action="resolve",
            entity_type=entity_type,
            entity_id=entity_id,
            context=context,
            start_path=start_path,
        )
    if resolved is not None and resolved.get("exists") is False:
        return resolved

    summarized = None
    if declaration.get("summarizable") and provider["tools"].get("summarize"):
        summarized = _call_runtime_reference_lookup(
            state,
            provider=provider,
            action="summarize",
            entity_type=entity_type,
            entity_id=entity_id,
            context=context,
            start_path=start_path,
        )
    if summarized is not None and summarized.get("exists") is False:
        return summarized
    if resolved is None:
        return summarized
    if summarized is None:
        return resolved
    return _merge_reference_payloads(resolved, summarized)


def _call_runtime_reference_lookup(
    state,
    *,
    provider: dict[str, Any],
    action: str,
    entity_type: str,
    entity_id: str,
    context: McpInvocationContext,
    start_path: Path,
) -> dict[str, object] | None:
    try:
        result = call_reference_tool(
            state,
            provider,
            action,
            context=context,
            arguments={"entity_type": entity_type, "entity_id": entity_id},
            start_path=start_path,
        )
    except Exception:
        logger.exception("Runtime reference %s failed for app `%s`.", action, provider["app_id"])
        return None
    normalized = normalize_reference_item(result, provider=provider, fallback_entity_type=entity_type)
    if normalized is None:
        logger.warning("Runtime reference %s returned invalid payload for app `%s`.", action, provider["app_id"])
        return None
    if "exists" in result:
        if result.get("exists") is False:
            normalized["exists"] = False
        else:
            normalized.pop("exists", None)
    return normalized


def _merge_reference_payloads(resolved: dict[str, object], summarized: dict[str, object]) -> dict[str, object]:
    merged = dict(resolved)
    for key in ("label", "summary"):
        value = summarized.get(key)
        if value:
            merged[key] = value
    for key in ("deep_link", "metadata", "exists"):
        if key in summarized:
            merged[key] = summarized[key]
    return merged


def _declared_manifest_bool(raw: dict[str, Any], declaration: dict[str, Any], key: str) -> bool:
    declared = bool(declaration.get(key))
    raw_value = raw.get(key, declaration.get(key))
    return declared and bool(raw_value)


def _deep_link(provider: dict[str, Any], raw_item: dict[str, Any]) -> str:
    app_id = str(provider["app_id"])
    public_app_id = str(provider.get("public_app_id") or app_id)
    app_page = _bounded_text(raw_item.get("app_page"), max_length=500)
    if app_page:
        return f"/app/{app_id}/{app_page.strip('/')}"
    deep_link = _bounded_text(raw_item.get("deep_link"), max_length=500)
    for candidate_app_id in {app_id, public_app_id}:
        if deep_link.startswith(f"/app/{candidate_app_id}/"):
            return f"/app/{app_id}/{deep_link.removeprefix(f'/app/{candidate_app_id}/').strip('/')}"
        if deep_link.startswith(f"/apps/{candidate_app_id}/"):
            return f"/app/{app_id}/{deep_link.removeprefix(f'/apps/{candidate_app_id}/').strip('/')}"
    return ""


def _bounded_text(value: object, *, max_length: int) -> str:
    return " ".join(str(value if value is not None else "").split()).strip()[:max_length]


def _reference_key(reference: dict[str, object]) -> str:
    if reference.get("type") == "entity":
        return (
            f"entity:{reference.get('app_id')}:{reference.get('entity_type')}:"
            f"{reference.get('entity_id')}"
        )
    return f"app:{reference.get('app_id')}"
