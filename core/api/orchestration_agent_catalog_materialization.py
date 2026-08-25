"""Verified materialization of planner and participant agent snapshots."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from core.api.orchestration_agent_catalog_models import (
    CatalogRevisionChanged,
    CompactAgentCatalogView,
    OrchestrationAgentCatalog,
    OrchestrationAgentCatalogSource,
)
from core.api.orchestration_agent_catalog_provider import (
    invoke_agent_provider,
    skill_catalog_app_id,
    string_items,
    with_root_active_context,
)
from core.inter_agent.errors import InterAgentOperationError, InterAgentValidationError
from core.inter_agent.models import AgentParticipantSnapshot
from core.inter_agent.orchestration_agent_capabilities import (
    CATALOG_AVAILABLE,
    CATALOG_UNAVAILABLE,
    EnabledWorkspaceSkillCatalog,
    build_orchestration_planner_catalog,
    enabled_workspace_skill_catalog,
    requires_explicit_catalog,
)


def refresh_orchestration_agent_catalog(
    source: OrchestrationAgentCatalogSource,
) -> OrchestrationAgentCatalog:
    if not source.provider_app_id:
        return _root_only_catalog(source, catalog_unavailable=True)
    for _attempt in range(3):
        before = _compact_catalog_view(source)
        try:
            snapshots = _materialize_catalog_snapshots(source, before.items)
        except CatalogRevisionChanged:
            continue
        after = _compact_catalog_view(source)
        if before.signature != after.signature:
            continue
        specialist_ids = tuple(
            sorted(
                agent_type_id
                for agent_type_id in snapshots
                if agent_type_id != source.root_snapshot.agent_type_id
            )
        )
        if specialist_ids != tuple(sorted(str(item["id"]) for item in after.items)):
            continue
        return _catalog_from_snapshots(source, snapshots)
    raise InterAgentOperationError(
        "Agent catalog changed repeatedly while preparing an orchestration decision; retry the decision."
    )


def _compact_catalog_view(source: OrchestrationAgentCatalogSource) -> CompactAgentCatalogView:
    payload = invoke_agent_provider(
        source,
        alias="agent-catalog",
        body={"action": "catalog.compact", "entity_type": "agent_type", "limit": 100},
    )
    items = tuple(
        dict(item)
        for item in payload.get("agent_types", [])
        if isinstance(item, dict)
        and item.get("enabled") is not False
        and str(item.get("id") or "").strip()
    )
    count = (
        (payload.get("counts") or {}).get("agent_types")
        if isinstance(payload.get("counts"), dict)
        else len(items)
    )
    encoded = json.dumps(
        {
            "count": count,
            "items": [_compact_revision_fields(item) for item in items],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return CompactAgentCatalogView(
        items=items,
        signature=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
    )


def _materialize_catalog_snapshots(
    source: OrchestrationAgentCatalogSource,
    items: tuple[dict[str, Any], ...],
) -> dict[str, AgentParticipantSnapshot]:
    snapshots = {source.root_snapshot.agent_type_id: source.root_snapshot}
    next_cache: dict[tuple[str, str], AgentParticipantSnapshot] = {}
    for item in items:
        agent_type_id = str(item.get("id") or "").strip()
        if agent_type_id == source.root_snapshot.agent_type_id:
            continue
        expected_revision = str(item.get("revision_id") or "").strip()
        snapshot = source.cache.get((agent_type_id, expected_revision)) if expected_revision else None
        if snapshot is None:
            snapshot = _materialize_agent_snapshot(source, item)
        snapshots[agent_type_id] = snapshot
        if expected_revision:
            next_cache[(agent_type_id, expected_revision)] = snapshot
    source.cache = next_cache
    return snapshots


def _materialize_agent_snapshot(
    source: OrchestrationAgentCatalogSource,
    compact_item: dict[str, Any],
) -> AgentParticipantSnapshot:
    agent_type_id = str(compact_item.get("id") or "").strip()
    definition_payload = invoke_agent_provider(
        source,
        alias="agent-catalog",
        body={"action": "get_agent_definition", "id": agent_type_id},
    )
    definition = definition_payload.get("agent_definition")
    if not definition_payload.get("exists") or not isinstance(definition, dict):
        raise CatalogRevisionChanged(agent_type_id)
    if not _compact_matches_definition(compact_item, definition):
        raise CatalogRevisionChanged(agent_type_id)
    prompt_payload = invoke_agent_provider(
        source,
        alias="agent-prompt-materializer",
        body={"action": "preview_prompt", "agent_type_id": agent_type_id},
    )
    expected_revision = str(compact_item.get("revision_id") or "").strip()
    definition_revision = str(definition.get("revision_id") or "").strip()
    prompt_revision = str(prompt_payload.get("revision_id") or "").strip()
    if expected_revision and (
        definition_revision != expected_revision or prompt_revision != expected_revision
    ):
        raise CatalogRevisionChanged(agent_type_id)
    if definition_revision and prompt_revision and definition_revision != prompt_revision:
        raise CatalogRevisionChanged(agent_type_id)
    return AgentParticipantSnapshot(
        agent_type_id=agent_type_id,
        label=str(definition.get("name") or agent_type_id).strip(),
        system_prompt=with_root_active_context(
            str(prompt_payload.get("rendered") or "").strip(),
            source.root_system_prompt,
        ),
        skill_ids=string_items(definition.get("skill_ids")),
        skill_catalog_app_id=skill_catalog_app_id(source, definition, prompt_payload),
        skill_activation_mode=str(definition.get("skill_activation_mode") or "implicit"),
        provider_id=source.provider_app_id,
        revision_id=(
            expected_revision
            or definition_revision
            or prompt_revision
            or str(definition.get("updated_at") or "").strip()
            or None
        ),
        metadata={
            "source": "orchestration_server_agent_catalog",
            "description": str(definition.get("description") or "").strip(),
            "definition_updated_at": str(definition.get("updated_at") or "").strip(),
        },
    )


def _catalog_from_snapshots(
    source: OrchestrationAgentCatalogSource,
    snapshots: dict[str, AgentParticipantSnapshot],
) -> OrchestrationAgentCatalog:
    items = [
        {
            "id": snapshot.agent_type_id,
            "name": snapshot.label,
            "description": str(snapshot.metadata.get("description") or ""),
            "skill_ids": list(snapshot.skill_ids),
            "skill_activation_mode": snapshot.skill_activation_mode,
            "enabled": True,
        }
        for agent_type_id, snapshot in sorted(snapshots.items())
        if agent_type_id != source.root_snapshot.agent_type_id
    ]
    enabled_skills = EnabledWorkspaceSkillCatalog(state=CATALOG_AVAILABLE, skill_ids=())
    if requires_explicit_catalog(source.root_snapshot, items):
        try:
            selected_skill_catalog_app_id = skill_catalog_app_id(source, {}, {})
        except InterAgentValidationError:
            enabled_skills = EnabledWorkspaceSkillCatalog(state=CATALOG_UNAVAILABLE, skill_ids=())
        else:
            enabled_skills = enabled_workspace_skill_catalog(
                workspace_id=source.workspace_id,
                start_path=source.start_path,
                app_id=selected_skill_catalog_app_id,
            )
    planner_catalog = build_orchestration_planner_catalog(
        source.root_snapshot,
        items,
        enabled_skills=enabled_skills,
    )
    encoded = json.dumps(
        {
            "agents": {
                agent_type_id: snapshot.digest()
                for agent_type_id, snapshot in sorted(snapshots.items())
            },
            "skills": {"state": enabled_skills.state, "ids": enabled_skills.skill_ids},
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return OrchestrationAgentCatalog(
        root_snapshot=source.root_snapshot,
        planner_catalog=planner_catalog,
        provider_app_id=source.provider_app_id,
        snapshots=dict(snapshots),
        revision_id=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
    )


def _root_only_catalog(
    source: OrchestrationAgentCatalogSource,
    *,
    catalog_unavailable: bool,
) -> OrchestrationAgentCatalog:
    enabled_skills = EnabledWorkspaceSkillCatalog(
        state=(
            CATALOG_UNAVAILABLE
            if catalog_unavailable and source.root_snapshot.skill_activation_mode == "explicit"
            else CATALOG_AVAILABLE
        ),
        skill_ids=(),
    )
    planner_catalog = build_orchestration_planner_catalog(
        source.root_snapshot,
        [],
        enabled_skills=enabled_skills,
    )
    revision_id = hashlib.sha256(
        f"{source.root_snapshot.digest()}:{enabled_skills.state}".encode("utf-8")
    ).hexdigest()
    return OrchestrationAgentCatalog(
        root_snapshot=source.root_snapshot,
        planner_catalog=planner_catalog,
        provider_app_id=source.provider_app_id,
        snapshots={source.root_snapshot.agent_type_id: source.root_snapshot},
        revision_id=revision_id,
    )


def _compact_revision_fields(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item.get(key)
        for key in (
            "id",
            "name",
            "description",
            "role_id",
            "skill_ids",
            "skill_activation_mode",
            "enabled",
            "updated_at",
            "revision_id",
        )
    }


def _compact_matches_definition(compact: dict[str, Any], definition: dict[str, Any]) -> bool:
    if str(definition.get("id") or "").strip() != str(compact.get("id") or "").strip():
        return False
    if definition.get("enabled") is False:
        return False
    if any(
        str(definition.get(key) or "").strip() != str(compact.get(key) or "").strip()
        for key in ("name", "description", "skill_activation_mode")
    ):
        return False
    return string_items(definition.get("skill_ids")) == string_items(compact.get("skill_ids"))
