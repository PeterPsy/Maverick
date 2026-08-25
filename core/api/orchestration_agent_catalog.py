"""Server-authoritative specialist catalog for hosted orchestration workers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.api.orchestration_agent_catalog_models import (
    OrchestrationAgentCatalog,
    OrchestrationAgentCatalogSource,
)
from core.api.orchestration_agent_catalog_provider import string_items
from core.apps.dependencies import resolve_app_dependencies
from core.apps.errors import AppHostingError
from core.inter_agent.models import AgentParticipantSnapshot, InterAgentParticipantRecord


CHAT_APP_ID = "chat"
AGENT_PROVIDER_ALIASES = ("agent-catalog", "agent-prompt-materializer")


def build_orchestration_agent_catalog(
    state: Any,
    *,
    workspace_id: str,
    created_by_user_id: str,
    root_session: Any,
    orchestrator: InterAgentParticipantRecord,
    start_path: Path,
) -> OrchestrationAgentCatalog:
    return build_orchestration_agent_catalog_source(
        state,
        workspace_id=workspace_id,
        created_by_user_id=created_by_user_id,
        root_session=root_session,
        orchestrator=orchestrator,
        start_path=start_path,
    ).refresh()


def build_orchestration_agent_catalog_source(
    state: Any,
    *,
    workspace_id: str,
    created_by_user_id: str,
    root_session: Any,
    orchestrator: InterAgentParticipantRecord,
    start_path: Path,
) -> OrchestrationAgentCatalogSource:
    root_snapshot = _root_snapshot(orchestrator)
    try:
        user = state.identity_store.get_user(created_by_user_id)
        provider_app_id = _selected_agent_provider(
            state,
            workspace_id=workspace_id,
            user=user,
            preferred_provider_id=str(root_session.source_app_id or "").strip(),
            start_path=start_path,
        )
        if not provider_app_id:
            raise AppHostingError("No shared Chat agent provider is selected.")
    except Exception:
        user = None
        provider_app_id = None
    return OrchestrationAgentCatalogSource(
        root_snapshot=root_snapshot,
        provider_app_id=provider_app_id,
        state=state,
        workspace_id=workspace_id,
        user=user,
        root_system_prompt=str(root_session.system_prompt or ""),
        start_path=start_path,
    )


def _root_snapshot(participant: InterAgentParticipantRecord) -> AgentParticipantSnapshot:
    document = participant.agent_snapshot if isinstance(participant.agent_snapshot, dict) else {}
    return AgentParticipantSnapshot(
        agent_type_id=str(document.get("agent_type_id") or participant.agent_type_id or "orchestrator"),
        label=str(document.get("label") or participant.label),
        system_prompt=str(document.get("system_prompt") or ""),
        skill_ids=string_items(document.get("skill_ids")),
        skill_catalog_app_id=str(document.get("skill_catalog_app_id") or "skills"),
        skill_activation_mode=str(document.get("skill_activation_mode") or "implicit"),
        provider_id=str(document.get("provider_id") or participant.provider_id or "").strip() or None,
        revision_id=str(document.get("revision_id") or "").strip() or None,
        metadata=document.get("metadata") if isinstance(document.get("metadata"), dict) else {},
    )


def _selected_agent_provider(
    state: Any,
    *,
    workspace_id: str,
    user: Any,
    preferred_provider_id: str,
    start_path: Path,
) -> str | None:
    dependencies = resolve_app_dependencies(
        state.app_store,
        workspace_id=workspace_id,
        consumer_app_id=CHAT_APP_ID,
        user=user,
        workspace_store=state.workspace_store,
        start_path=start_path,
    )
    by_alias = {
        str(item.get("alias") or ""): item
        for item in dependencies.get("dependencies", [])
        if isinstance(item, dict)
    }
    provider_sets = [_dependency_provider_ids(by_alias.get(alias)) for alias in AGENT_PROVIDER_ALIASES]
    if any(not items for items in provider_sets):
        return None
    shared = set(provider_sets[0]).intersection(*provider_sets[1:])
    if preferred_provider_id in shared:
        return preferred_provider_id
    return sorted(shared)[0] if shared else None


def _dependency_provider_ids(dependency: dict[str, Any] | None) -> list[str]:
    if dependency is None:
        return []
    selected = string_items(dependency.get("selected_provider_app_ids"))
    if selected and dependency.get("status") == "resolved":
        return selected
    if dependency.get("status") != "optional_unset" or dependency.get("cardinality") != "one":
        return []
    candidates = dependency.get("candidates") if isinstance(dependency.get("candidates"), list) else []
    return [
        str(item.get("app_id") or "").strip()
        for item in candidates
        if isinstance(item, dict)
        and str(item.get("app_id") or "").strip()
        and "backend" in {str(surface) for surface in item.get("surfaces", [])}
    ]
