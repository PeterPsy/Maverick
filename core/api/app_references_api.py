"""Generic app-owned reference discovery and lookup API."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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
REFERENCE_SEARCH_MAX_WORKERS = 8


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
    search_specs: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    candidates: list[tuple[dict[str, Any], int, str]] = []
    errors: list[dict[str, str]] = []
    for provider_index, provider in enumerate(reference_providers(state, context=context, start_path=start_path)):
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
            search_specs.append((provider_index, provider, entity))
    for provider_index, provider, entity, result, error in _run_reference_searches(
        state,
        search_specs,
        context=mcp_context,
        query=query,
        limit=limit,
        start_path=start_path,
    ):
        if error is not None:
            logger.error(
                "Reference search failed for app `%s`.",
                provider["app_id"],
                exc_info=(type(error), error, error.__traceback__),
            )
            errors.append({"app_id": provider["app_id"], "error": "reference_search_failed"})
            continue
        for raw_item in _raw_result_items(result):
            normalized = normalize_reference_item(raw_item, provider=provider, fallback_entity_type=entity["entity_type"])
            if normalized is not None:
                candidates.append((normalized, provider_index, str(entity["entity_type"])))
    return {"query": query, "items": _ordered_search_items(candidates, query=query, limit=limit), "errors": errors}


def _run_reference_searches(
    state,
    search_specs: list[tuple[int, dict[str, Any], dict[str, Any]]],
    *,
    context,
    query: str,
    limit: int,
    start_path: Path,
) -> list[tuple[int, dict[str, Any], dict[str, Any], dict[str, Any], BaseException | None]]:
    if not search_specs:
        return []
    if len(search_specs) == 1:
        return [_call_reference_search(state, search_specs[0], context=context, query=query, limit=limit, start_path=start_path)]
    max_workers = min(REFERENCE_SEARCH_MAX_WORKERS, len(search_specs))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="maverick-reference-search") as executor:
        futures = [
            executor.submit(_call_reference_search, state, spec, context=context, query=query, limit=limit, start_path=start_path)
            for spec in search_specs
        ]
        return [future.result() for future in futures]


def _call_reference_search(
    state,
    spec: tuple[int, dict[str, Any], dict[str, Any]],
    *,
    context,
    query: str,
    limit: int,
    start_path: Path,
) -> tuple[int, dict[str, Any], dict[str, Any], dict[str, Any], BaseException | None]:
    provider_index, provider, entity = spec
    try:
        result = call_reference_tool(
            state,
            provider,
            "search",
            context=context,
            arguments={"entity_type": entity["entity_type"], "query": query, "limit": limit},
            start_path=start_path,
        )
    except Exception as error:
        return provider_index, provider, entity, {}, error
    if not isinstance(result, dict):
        return provider_index, provider, entity, {}, None
    return provider_index, provider, entity, result, None


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


def _ordered_search_items(
    candidates: list[tuple[dict[str, Any], int, str]],
    *,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    if not query.strip():
        return _round_robin_search_items(candidates, limit=limit)
    scored = [
        (_reference_search_score(item, query), index, item)
        for index, (item, _provider_index, _entity_type) in enumerate(candidates)
    ]
    scored.sort(key=lambda candidate: (-candidate[0], candidate[1]))
    return [item for _score, _index, item in scored[:limit]]


def _round_robin_search_items(candidates: list[tuple[dict[str, Any], int, str]], *, limit: int) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    by_group: dict[tuple[int, str, str], list[dict[str, Any]]] = {}
    for item, provider_index, entity_type in candidates:
        group_key = (provider_index, str(item.get("app_id") or ""), entity_type)
        group = by_group.get(group_key)
        if group is None:
            group = []
            by_group[group_key] = group
            groups.append(group)
        group.append(item)

    ordered: list[dict[str, Any]] = []
    while groups and len(ordered) < limit:
        next_groups: list[list[dict[str, Any]]] = []
        for group in groups:
            if not group:
                continue
            ordered.append(group.pop(0))
            if group:
                next_groups.append(group)
            if len(ordered) >= limit:
                break
        groups = next_groups
    return ordered


def _reference_search_score(item: dict[str, Any], query: str) -> int:
    tokens = _query_tokens(query)
    if not tokens:
        return 0
    full_query = " ".join(tokens)
    label = _search_text(item.get("label"))
    summary = _search_text(item.get("summary"))
    identity = _search_text(
        " ".join(
            str(item.get(key) or "")
            for key in (
                "app_id",
                "entity_type",
                "entity_id",
                "deep_link",
            )
        )
    )
    score = 0
    if label == full_query:
        score += 1000
    elif label.startswith(full_query):
        score += 500
    elif full_query in label:
        score += 300
    if full_query in summary:
        score += 80
    if full_query in identity:
        score += 40
    for token in tokens:
        if token in label:
            score += 50
        if token in summary:
            score += 15
        if token in identity:
            score += 5
    return score


def _query_tokens(query: str) -> list[str]:
    return [token for token in _search_text(query).split() if token]


def _search_text(value: object) -> str:
    return " ".join(str(value if value is not None else "").casefold().split())


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
