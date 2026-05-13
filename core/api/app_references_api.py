"""Generic app-owned reference discovery and lookup API."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.api.http import StartResponse, json_response, read_json_body
from core.api.app_reference_payloads import (
    manifest_provider_payload,
    normalize_reference_item,
)
from core.api.app_reference_providers import (
    call_reference_tool,
    mcp_context_for_request,
    reference_providers,
)
from core.api.session_api import RequestSession


logger = logging.getLogger(__name__)


def handle_app_references_api(
    state,
    environ: dict,
    start_response: StartResponse,
    *,
    context: RequestSession | None,
    start_path: Path,
) -> list[bytes] | None:
    """Handle generic reference discovery/search/resolve routes."""
    path = str(environ.get("PATH_INFO") or "/")
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    if path not in {
        "/api/app-references/manifest",
        "/api/app-references/search",
        "/api/app-references/resolve",
        "/api/app-references/summarize",
    }:
        return None
    if context is None:
        return json_response(start_response, {"error": "authentication_required"}, status="401 Unauthorized")
    if path == "/api/app-references/manifest":
        if method != "GET":
            return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
        return json_response(start_response, _reference_manifest(state, context=context, start_path=start_path))
    if method != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    body = read_json_body(environ)
    if path == "/api/app-references/search":
        return json_response(start_response, _search_references(state, context=context, body=body, start_path=start_path))
    if path == "/api/app-references/resolve":
        payload, status = _lookup_reference(state, context=context, body=body, action="resolve", start_path=start_path)
        return json_response(start_response, payload, status=status)
    payload, status = _lookup_reference(state, context=context, body=body, action="summarize", start_path=start_path)
    return json_response(start_response, payload, status=status)


def _search_references(state, *, context: RequestSession, body: dict[str, Any], start_path: Path) -> dict[str, Any]:
    query = _bounded_text(body.get("query"), max_length=240)
    limit = _positive_int(body.get("limit"), default=8, maximum=25)
    selected_app_ids = set(_string_list(body.get("app_ids")))
    selected_entity_types = set(_string_list(body.get("entity_types")))
    mcp_context = mcp_context_for_request(state, context)
    items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for provider in reference_providers(state, context=context, start_path=start_path):
        if selected_app_ids and provider["app_id"] not in selected_app_ids:
            continue
        if not provider["tools"].get("search"):
            continue
        searchable_entities = [
            entity
            for entity in provider["entities"]
            if entity.get("searchable") and (not selected_entity_types or entity.get("entity_type") in selected_entity_types)
        ]
        for entity in searchable_entities:
            try:
                result = call_reference_tool(
                    state,
                    provider,
                    "search",
                    context=mcp_context,
                    arguments={"entity_type": entity["entity_type"], "query": query, "limit": limit},
                    start_path=start_path,
                )
            except Exception:
                logger.exception("Reference search failed for app `%s`.", provider["app_id"])
                errors.append({"app_id": provider["app_id"], "error": "reference_search_failed"})
                continue
            for raw_item in _raw_result_items(result):
                normalized = normalize_reference_item(raw_item, provider=provider, fallback_entity_type=entity["entity_type"])
                if normalized is not None:
                    items.append(normalized)
    return {"query": query, "items": items[:limit], "errors": errors}


def _lookup_reference(
    state,
    *,
    context: RequestSession,
    body: dict[str, Any],
    action: str,
    start_path: Path,
) -> tuple[dict[str, Any], str]:
    app_id = _bounded_text(body.get("app_id"), max_length=120)
    entity_type = _bounded_text(body.get("entity_type"), max_length=120)
    entity_id = _bounded_text(body.get("entity_id") or body.get("id"), max_length=240)
    if not app_id or not entity_type or not entity_id:
        return {"error": "reference_identity_required"}, "400 Bad Request"
    provider = next(
        (item for item in reference_providers(state, context=context, start_path=start_path) if item["app_id"] == app_id),
        None,
    )
    if provider is None:
        return {"error": "reference_provider_not_found"}, "404 Not Found"
    declaration = next((item for item in provider["entities"] if item.get("entity_type") == entity_type), None)
    if declaration is None:
        return {"error": "reference_entity_type_not_found"}, "404 Not Found"
    if not declaration.get("resolvable" if action == "resolve" else "summarizable"):
        return {"error": f"reference_{action}_unsupported"}, "400 Bad Request"
    if not provider["tools"].get(action):
        return {"error": f"reference_{action}_unavailable"}, "404 Not Found"
    try:
        result = call_reference_tool(
            state,
            provider,
            action,
            context=mcp_context_for_request(state, context),
            arguments={"entity_type": entity_type, "entity_id": entity_id},
            start_path=start_path,
        )
    except Exception:
        logger.exception("Reference %s failed for app `%s`.", action, app_id)
        return {"error": f"reference_{action}_failed"}, "500 Internal Server Error"
    normalized = normalize_reference_item(result, provider=provider, fallback_entity_type=entity_type)
    if normalized is None:
        return {"error": "reference_payload_invalid"}, "500 Internal Server Error"
    if "exists" in result:
        normalized["exists"] = bool(result.get("exists"))
    return normalized, "200 OK"


def _reference_manifest(state, *, context: RequestSession, start_path: Path) -> dict[str, Any]:
    mcp_context = mcp_context_for_request(state, context)
    items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for provider in reference_providers(state, context=context, start_path=start_path):
        try:
            items.append(manifest_provider_payload(state, provider, context=mcp_context, start_path=start_path))
        except Exception:
            logger.exception("Reference manifest failed for app `%s`.", provider["app_id"])
            errors.append({"app_id": provider["app_id"], "error": "reference_manifest_failed"})
    return {"workspace_id": context.workspace_id, "items": items, "errors": errors}


def _raw_result_items(result: dict[str, Any]) -> list[object]:
    for key in ("items", "results", "references"):
        value = result.get(key)
        if isinstance(value, list):
            return value
    return []


def _bounded_text(value: object, *, max_length: int) -> str:
    return " ".join(str(value if value is not None else "").split()).strip()[:max_length]


def _positive_int(value: object, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value) if value not in {None, ""} else default
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, maximum))


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_bounded_text(item, max_length=120) for item in value if _bounded_text(item, max_length=120)]
