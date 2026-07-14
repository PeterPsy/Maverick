"""Payload normalization for app-owned references."""

from __future__ import annotations

from collections import OrderedDict
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
from threading import Event, Lock
import time
from typing import Any

from core.api.app_reference_providers import (
    call_reference_tool,
    mcp_context_for_request,
    public_provider_payload,
    reference_providers_by_app_id,
    reference_tool_runner,
    reference_providers,
    visible_workspace_apps_by_app_id,
    visible_workspace_apps,
)
from core.api.session_api import RequestSession
from core.mcp.models import McpInvocationContext
from core.observability.service import record_platform_metric

logger = logging.getLogger(__name__)
RUNTIME_APP_REFERENCE_CACHE_TTL_SECONDS = 300.0
RUNTIME_APP_REFERENCE_CACHE_MAX_ENTRIES = 1024
_RUNTIME_APP_REFERENCE_CACHE: OrderedDict[str, tuple[float, "RuntimeAppReferenceMaterializationResult"]] = OrderedDict()
_RUNTIME_APP_REFERENCE_CACHE_LOCK = Lock()
_RUNTIME_APP_REFERENCE_CACHE_EVICTIONS = 0
_RUNTIME_APP_REFERENCE_IN_FLIGHT: dict[str, Event] = {}
_RUNTIME_APP_REFERENCE_IN_FLIGHT_LOCK = Lock()


@dataclass(frozen=True)
class RuntimeAppReferenceCacheStats:
    size: int
    evictions: int
    max_entries: int


@dataclass(frozen=True)
class RuntimeAppReferenceMaterializationResult:
    references: list[dict[str, object]]
    reference_action_timings: list[dict[str, object]]
    reference_cache_hit: bool = False
    reference_fingerprint: str = ""


def clear_runtime_app_reference_materialization_cache() -> None:
    """Clear the non-persistent runtime app reference materialization cache."""
    global _RUNTIME_APP_REFERENCE_CACHE_EVICTIONS
    with _RUNTIME_APP_REFERENCE_CACHE_LOCK:
        _RUNTIME_APP_REFERENCE_CACHE.clear()
        _RUNTIME_APP_REFERENCE_CACHE_EVICTIONS = 0


def runtime_app_reference_materialization_cache_stats() -> RuntimeAppReferenceCacheStats:
    """Return redaction-safe runtime app reference cache stats."""
    with _RUNTIME_APP_REFERENCE_CACHE_LOCK:
        return RuntimeAppReferenceCacheStats(
            size=len(_RUNTIME_APP_REFERENCE_CACHE),
            evictions=_RUNTIME_APP_REFERENCE_CACHE_EVICTIONS,
            max_entries=_runtime_app_reference_cache_max_entries(),
        )


class RuntimeAppReferenceRequestContext:
    """Request-local discovery cache for runtime app reference handling."""

    def __init__(self, state, *, context: RequestSession, start_path: Path) -> None:
        self._state = state
        self._context = context
        self._start_path = start_path
        self._visible_apps: dict[str, dict[str, Any]] | None = None
        self._visible_apps_by_app_id: dict[str, dict[str, Any]] = {}
        self._providers_by_app_id: dict[str, dict[str, Any]] | None = None
        self._targeted_providers_by_app_id: dict[str, dict[str, Any]] = {}

    def visible_apps(self) -> dict[str, dict[str, Any]]:
        if self._visible_apps is None:
            self._visible_apps = visible_workspace_apps(
                self._state,
                context=self._context,
                start_path=self._start_path,
            )
        return self._visible_apps

    def providers_by_app_id(self) -> dict[str, dict[str, Any]]:
        if self._providers_by_app_id is None:
            self._providers_by_app_id = {
                provider["app_id"]: provider
                for provider in reference_providers(
                    self._state,
                    context=self._context,
                    start_path=self._start_path,
                )
            }
        return self._providers_by_app_id

    def visible_apps_for_app_ids(self, app_ids: set[str]) -> dict[str, dict[str, Any]]:
        if not app_ids:
            return {}
        if self._visible_apps is not None:
            return {app_id: self._visible_apps[app_id] for app_id in app_ids if app_id in self._visible_apps}
        missing = {app_id for app_id in app_ids if app_id not in self._visible_apps_by_app_id}
        if missing:
            self._visible_apps_by_app_id.update(
                visible_workspace_apps_by_app_id(
                    self._state,
                    context=self._context,
                    start_path=self._start_path,
                    app_ids=missing,
                )
            )
        return {app_id: self._visible_apps_by_app_id[app_id] for app_id in app_ids if app_id in self._visible_apps_by_app_id}

    def providers_for_app_ids(self, app_ids: set[str]) -> dict[str, dict[str, Any]]:
        if not app_ids:
            return {}
        if self._providers_by_app_id is not None:
            return {app_id: self._providers_by_app_id[app_id] for app_id in app_ids if app_id in self._providers_by_app_id}
        missing = {app_id for app_id in app_ids if app_id not in self._targeted_providers_by_app_id}
        if missing:
            self._targeted_providers_by_app_id.update(
                reference_providers_by_app_id(
                    self._state,
                    context=self._context,
                    start_path=self._start_path,
                    app_ids=missing,
                )
            )
        return {
            app_id: self._targeted_providers_by_app_id[app_id]
            for app_id in app_ids
            if app_id in self._targeted_providers_by_app_id
        }


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
    reference_context: RuntimeAppReferenceRequestContext | None = None,
) -> list[dict[str, object]]:
    """Verify client-submitted references and enrich entities from owning apps."""
    return materialize_runtime_app_references_with_metrics(
        state,
        context=context,
        references=references,
        start_path=start_path,
        reference_context=reference_context,
    ).references


def materialize_runtime_app_references_with_metrics(
    state,
    *,
    context: RequestSession,
    references: list[dict[str, object]],
    start_path: Path,
    reference_context: RuntimeAppReferenceRequestContext | None = None,
    session_id: str = "",
) -> RuntimeAppReferenceMaterializationResult:
    """Verify client-submitted references and enrich entities with redaction-safe timings."""
    if not references:
        return RuntimeAppReferenceMaterializationResult(references=[], reference_action_timings=[])
    runtime_reference_context = reference_context or RuntimeAppReferenceRequestContext(
        state,
        context=context,
        start_path=start_path,
    )
    needs_entity_providers = any(_reference_type(reference) == "entity" for reference in references)
    needs_visible_apps = any(_reference_type(reference) != "entity" for reference in references)
    visible_apps = (
        runtime_reference_context.visible_apps_for_app_ids(_reference_app_ids(references, entity_refs=False))
        if needs_visible_apps
        else {}
    )
    providers_by_app_id = (
        runtime_reference_context.providers_for_app_ids(_reference_app_ids(references, entity_refs=True))
        if needs_entity_providers
        else {}
    )
    mcp_context = mcp_context_for_request(state, context)
    reference_fingerprint = _runtime_reference_cache_fingerprint(
        context=context,
        mcp_context=mcp_context,
        session_id=session_id,
        references=references,
        visible_apps=visible_apps,
        providers_by_app_id=providers_by_app_id,
    )
    while True:
        cached = _cached_runtime_app_reference_result(reference_fingerprint)
        if cached is not None:
            return cached
        owns_materialization, in_flight = _claim_runtime_app_reference_materialization(reference_fingerprint)
        if owns_materialization:
            break
        in_flight.wait()

    try:
        reference_action_timings: list[dict[str, object]] = []
        runner = None

        def get_runner():
            nonlocal runner
            if runner is None:
                runner = reference_tool_runner(state, context=mcp_context, start_path=start_path)
            return runner

        materialized: list[dict[str, object]] = []
        seen: set[str] = set()
        for reference in references:
            app_id = _bounded_text(reference.get("app_id"), max_length=120)
            if not app_id:
                continue
            if _reference_type(reference) == "entity":
                payload = _materialize_runtime_entity_reference(
                    state,
                    provider=providers_by_app_id.get(app_id),
                    reference=reference,
                    context=mcp_context,
                    start_path=start_path,
                    runner_factory=get_runner,
                    action_timings=reference_action_timings,
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
        result = RuntimeAppReferenceMaterializationResult(
            references=materialized,
            reference_action_timings=reference_action_timings,
            reference_fingerprint=reference_fingerprint,
        )
        _cache_runtime_app_reference_result(
            state,
            result,
            workspace_id=context.workspace_id,
            session_id=session_id,
        )
        return result
    finally:
        _release_runtime_app_reference_materialization(reference_fingerprint)


def _claim_runtime_app_reference_materialization(reference_fingerprint: str) -> tuple[bool, Event]:
    with _RUNTIME_APP_REFERENCE_IN_FLIGHT_LOCK:
        in_flight = _RUNTIME_APP_REFERENCE_IN_FLIGHT.get(reference_fingerprint)
        if in_flight is not None:
            return False, in_flight
        in_flight = Event()
        _RUNTIME_APP_REFERENCE_IN_FLIGHT[reference_fingerprint] = in_flight
        return True, in_flight


def _release_runtime_app_reference_materialization(reference_fingerprint: str) -> None:
    with _RUNTIME_APP_REFERENCE_IN_FLIGHT_LOCK:
        in_flight = _RUNTIME_APP_REFERENCE_IN_FLIGHT.pop(reference_fingerprint, None)
    if in_flight is not None:
        in_flight.set()


def validate_runtime_app_references(
    state,
    *,
    context: RequestSession,
    references: list[dict[str, object]],
    start_path: Path,
    reference_context: RuntimeAppReferenceRequestContext | None = None,
) -> list[dict[str, object]]:
    """Verify client-submitted references without invoking app-owned MCP tools."""
    if not references:
        return []
    runtime_reference_context = reference_context or RuntimeAppReferenceRequestContext(
        state,
        context=context,
        start_path=start_path,
    )
    needs_entity_providers = any(_reference_type(reference) == "entity" for reference in references)
    needs_visible_apps = any(_reference_type(reference) != "entity" for reference in references)
    visible_apps = (
        runtime_reference_context.visible_apps_for_app_ids(_reference_app_ids(references, entity_refs=False))
        if needs_visible_apps
        else {}
    )
    providers_by_app_id = (
        runtime_reference_context.providers_for_app_ids(_reference_app_ids(references, entity_refs=True))
        if needs_entity_providers
        else {}
    )
    validated: list[dict[str, object]] = []
    seen: set[str] = set()
    for reference in references:
        app_id = _bounded_text(reference.get("app_id"), max_length=120)
        if not app_id:
            continue
        if _reference_type(reference) == "entity":
            payload = _validate_runtime_entity_reference(
                provider=providers_by_app_id.get(app_id),
                reference=reference,
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
        validated.append(payload)
    return validated


def _reference_type(reference: dict[str, object]) -> str:
    return str(reference.get("type") or "app").strip().lower()


def _reference_app_ids(references: list[dict[str, object]], *, entity_refs: bool) -> set[str]:
    return {
        app_id
        for reference in references
        if (_reference_type(reference) == "entity") == entity_refs
        for app_id in [_bounded_text(reference.get("app_id"), max_length=120)]
        if app_id
    }


def _validate_runtime_entity_reference(
    *,
    provider: dict[str, Any] | None,
    reference: dict[str, object],
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
    return {
        "type": "entity",
        "app_id": provider["app_id"],
        "entity_type": entity_type,
        "entity_id": entity_id,
        "label": entity_id,
        "summary": "",
        **_safe_reference_metadata_payload(reference),
    }


def _materialize_runtime_entity_reference(
    state,
    *,
    provider: dict[str, Any] | None,
    reference: dict[str, object],
    context: McpInvocationContext,
    start_path: Path,
    runner_factory,
    action_timings: list[dict[str, object]],
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
            runner_factory=runner_factory,
            action_timings=action_timings,
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
            runner_factory=runner_factory,
            action_timings=action_timings,
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
    runner_factory,
    action_timings: list[dict[str, object]],
) -> dict[str, object] | None:
    started_at = time.perf_counter()
    status = "completed"
    try:
        result = call_reference_tool(
            state,
            provider,
            action,
            context=context,
            arguments={"entity_type": entity_type, "entity_id": entity_id},
            start_path=start_path,
            runner=runner_factory(),
        )
    except Exception:
        status = "failed"
        _append_reference_action_timing(
            action_timings,
            provider=provider,
            entity_type=entity_type,
            action=action,
            status=status,
            elapsed_ms=(time.perf_counter() - started_at) * 1000,
        )
        logger.exception("Runtime reference %s failed for app `%s`.", action, provider["app_id"])
        return None
    normalized = normalize_reference_item(result, provider=provider, fallback_entity_type=entity_type)
    if normalized is None:
        status = "invalid_payload"
        _append_reference_action_timing(
            action_timings,
            provider=provider,
            entity_type=entity_type,
            action=action,
            status=status,
            elapsed_ms=(time.perf_counter() - started_at) * 1000,
        )
        logger.warning("Runtime reference %s returned invalid payload for app `%s`.", action, provider["app_id"])
        return None
    if "exists" in result:
        if result.get("exists") is False:
            normalized["exists"] = False
            status = "exists_false"
        else:
            normalized.pop("exists", None)
    _append_reference_action_timing(
        action_timings,
        provider=provider,
        entity_type=entity_type,
        action=action,
        status=status,
        elapsed_ms=(time.perf_counter() - started_at) * 1000,
    )
    return normalized


def _append_reference_action_timing(
    timings: list[dict[str, object]],
    *,
    provider: dict[str, Any],
    entity_type: str,
    action: str,
    status: str,
    elapsed_ms: float,
) -> None:
    timings.append(
        {
            "app_id": str(provider.get("app_id") or ""),
            "entity_type": entity_type,
            "action": action,
            "status": status,
            "elapsed_ms": round(elapsed_ms, 3),
        }
    )


def _cached_runtime_app_reference_result(reference_fingerprint: str) -> RuntimeAppReferenceMaterializationResult | None:
    global _RUNTIME_APP_REFERENCE_CACHE_EVICTIONS
    if not reference_fingerprint:
        return None
    now = time.monotonic()
    with _RUNTIME_APP_REFERENCE_CACHE_LOCK:
        cached = _RUNTIME_APP_REFERENCE_CACHE.get(reference_fingerprint)
        if cached is None:
            return None
        expires_at, result = cached
        if expires_at <= now:
            _RUNTIME_APP_REFERENCE_CACHE.pop(reference_fingerprint, None)
            _RUNTIME_APP_REFERENCE_CACHE_EVICTIONS += 1
            return None
        _RUNTIME_APP_REFERENCE_CACHE.move_to_end(reference_fingerprint)
    return RuntimeAppReferenceMaterializationResult(
        references=deepcopy(result.references),
        reference_action_timings=[],
        reference_cache_hit=True,
        reference_fingerprint=result.reference_fingerprint,
    )


def _cache_runtime_app_reference_result(
    state,
    result: RuntimeAppReferenceMaterializationResult,
    *,
    workspace_id: str,
    session_id: str,
) -> None:
    global _RUNTIME_APP_REFERENCE_CACHE_EVICTIONS
    if not result.reference_fingerprint:
        return
    cached = RuntimeAppReferenceMaterializationResult(
        references=deepcopy(result.references),
        reference_action_timings=[],
        reference_cache_hit=False,
        reference_fingerprint=result.reference_fingerprint,
    )
    now = time.monotonic()
    with _RUNTIME_APP_REFERENCE_CACHE_LOCK:
        evictions = _prune_expired_runtime_app_reference_cache_locked(now)
        _RUNTIME_APP_REFERENCE_CACHE[result.reference_fingerprint] = (
            now + RUNTIME_APP_REFERENCE_CACHE_TTL_SECONDS,
            cached,
        )
        _RUNTIME_APP_REFERENCE_CACHE.move_to_end(result.reference_fingerprint)
        evictions += _bound_runtime_app_reference_cache_locked()
        _RUNTIME_APP_REFERENCE_CACHE_EVICTIONS += evictions
        cache_size = len(_RUNTIME_APP_REFERENCE_CACHE)
    _record_runtime_app_reference_cache_metrics(
        state,
        workspace_id=workspace_id,
        session_id=session_id,
        cache_size=cache_size,
        evictions=evictions,
    )


def _runtime_app_reference_cache_max_entries() -> int:
    with suppress(Exception):
        return max(1, int(RUNTIME_APP_REFERENCE_CACHE_MAX_ENTRIES))
    return 1024


def _prune_expired_runtime_app_reference_cache_locked(now: float) -> int:
    expired = [fingerprint for fingerprint, (expires_at, _result) in _RUNTIME_APP_REFERENCE_CACHE.items() if expires_at <= now]
    for fingerprint in expired:
        _RUNTIME_APP_REFERENCE_CACHE.pop(fingerprint, None)
    return len(expired)


def _bound_runtime_app_reference_cache_locked() -> int:
    evictions = 0
    max_entries = _runtime_app_reference_cache_max_entries()
    while len(_RUNTIME_APP_REFERENCE_CACHE) > max_entries:
        _RUNTIME_APP_REFERENCE_CACHE.popitem(last=False)
        evictions += 1
    return evictions


def _record_runtime_app_reference_cache_metrics(
    state,
    *,
    workspace_id: str,
    session_id: str,
    cache_size: int,
    evictions: int,
) -> None:
    observability_store = getattr(state, "observability_store", None)
    if observability_store is None:
        return
    tags = {"cache": "runtime_app_references"}
    with suppress(Exception):
        record_platform_metric(
            observability_store,
            metric_name="reference_cache_size",
            kind="gauge",
            value=cache_size,
            workspace_id=workspace_id,
            runtime_session_id=session_id or None,
            tags=tags,
        )
        if evictions:
            record_platform_metric(
                observability_store,
                metric_name="reference_cache_evictions",
                kind="counter",
                value=evictions,
                workspace_id=workspace_id,
                runtime_session_id=session_id or None,
                tags=tags,
            )


def _runtime_reference_cache_fingerprint(
    *,
    context: RequestSession,
    mcp_context: McpInvocationContext,
    session_id: str,
    references: list[dict[str, object]],
    visible_apps: dict[str, dict[str, Any]],
    providers_by_app_id: dict[str, dict[str, Any]],
) -> str:
    payload = {
        "workspace_id": context.workspace_id,
        "user_id": context.user.user_id,
        "platform_role": context.user.platform_role,
        "workspace_role": mcp_context.workspace_role or "",
        "effective_mode": mcp_context.effective_mode,
        "session_id": session_id if _references_require_session_cache_scope(references, providers_by_app_id) else "",
        "references": [
            _reference_cache_key_payload(
                reference,
                visible_apps=visible_apps,
                providers_by_app_id=providers_by_app_id,
            )
            for reference in references
            if isinstance(reference, dict)
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _references_require_session_cache_scope(
    references: list[dict[str, object]],
    providers_by_app_id: dict[str, dict[str, Any]],
) -> bool:
    if not references:
        return True
    for reference in references:
        if _reference_type(reference) != "entity":
            return True
        app_id = _bounded_text(reference.get("app_id"), max_length=120)
        entity_type = _bounded_text(reference.get("entity_type"), max_length=120)
        provider = providers_by_app_id.get(app_id)
        declaration = next(
            (
                item
                for item in (provider or {}).get("entities", [])
                if isinstance(item, dict) and item.get("entity_type") == entity_type
            ),
            None,
        )
        if not isinstance(declaration, dict) or declaration.get("cache_scope") != "workspace_user":
            return True
    return False


def _reference_cache_key_payload(
    reference: dict[str, object],
    *,
    visible_apps: dict[str, dict[str, Any]],
    providers_by_app_id: dict[str, dict[str, Any]],
) -> dict[str, object]:
    app_id = _bounded_text(reference.get("app_id"), max_length=120)
    entity_type = _bounded_text(reference.get("entity_type"), max_length=120)
    provider = providers_by_app_id.get(app_id)
    return {
        "type": _reference_type(reference),
        "app_id": app_id,
        "entity_type": entity_type,
        "entity_id": _bounded_text(reference.get("entity_id") or reference.get("id"), max_length=240),
        "action": "runtime_materialize",
        "app": _visible_app_cache_key_payload(visible_apps.get(app_id)),
        "provider": _provider_cache_key_payload(provider, entity_type=entity_type),
        "metadata": _safe_reference_metadata(reference),
    }


def _visible_app_cache_key_payload(app: dict[str, Any] | None) -> dict[str, object]:
    if app is None:
        return {}
    return {
        "app_id": app.get("app_id") or "",
        "public_app_id": app.get("public_app_id") or "",
        "mount_app_id": app.get("mount_app_id") or "",
        "binding_fingerprint": app.get("binding_fingerprint") or "",
        "name": app.get("name") or "",
    }


def _provider_cache_key_payload(provider: dict[str, Any] | None, *, entity_type: str) -> dict[str, object]:
    if provider is None:
        return {}
    declaration = next((item for item in provider.get("entities", []) if item.get("entity_type") == entity_type), {})
    return {
        "app_id": provider.get("app_id") or "",
        "public_app_id": provider.get("public_app_id") or "",
        "mount_app_id": provider.get("mount_app_id") or "",
        "tool_owner_app_id": provider.get("tool_owner_app_id") or "",
        "binding_fingerprint": provider.get("binding_fingerprint") or "",
        "tools": dict(provider.get("tools") if isinstance(provider.get("tools"), dict) else {}),
        "entity": {
            "entity_type": declaration.get("entity_type") or "",
            "resolvable": bool(declaration.get("resolvable")),
            "summarizable": bool(declaration.get("summarizable")),
            "deep_link_supported": bool(declaration.get("deep_link_supported")),
            "cache_scope": declaration.get("cache_scope") or "session",
        },
    }


def _safe_reference_metadata_payload(reference: dict[str, object]) -> dict[str, object]:
    metadata = _safe_reference_metadata(reference)
    return {"metadata": metadata} if metadata else {}


def _safe_reference_metadata(reference: dict[str, object]) -> dict[str, str]:
    raw_metadata = reference.get("metadata")
    if not isinstance(raw_metadata, dict):
        return {}
    safe: dict[str, str] = {}
    for key in ("sha256", "modified_at", "source_updated_at", "fingerprint"):
        value = _bounded_text(raw_metadata.get(key), max_length=240)
        if value:
            safe[key] = value
    return safe


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
