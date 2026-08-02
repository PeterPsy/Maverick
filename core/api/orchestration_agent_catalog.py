"""Server-authoritative specialist catalog for hosted orchestration workers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.apps.dependencies import resolve_app_dependencies
from core.apps.errors import AppHostingError
from core.apps.runtime_requests import invoke_dependency_backend_request
from core.inter_agent.errors import InterAgentValidationError
from core.inter_agent.models import AgentParticipantSnapshot, InterAgentParticipantRecord
from core.skills.runtime_catalog import (
    selected_runtime_skill_catalog_app_id_for_source_app,
    validate_runtime_skill_catalog_provider_app_id,
)


CHAT_APP_ID = "chat"
AGENT_PROVIDER_ALIASES = ("agent-catalog", "agent-prompt-materializer")
ACTIVE_APP_CONTEXT_HEADER = "Current shell context:"


@dataclass
class OrchestrationAgentCatalog:
    root_snapshot: AgentParticipantSnapshot
    prompt_entries: tuple[str, ...]
    provider_app_id: str | None
    agent_type_ids: frozenset[str]
    state: Any
    workspace_id: str
    user: Any
    root_system_prompt: str
    start_path: Path
    cache: dict[str, AgentParticipantSnapshot] = field(default_factory=dict)

    def resolve(self, agent_type_id: str) -> AgentParticipantSnapshot:
        normalized = str(agent_type_id or "").strip()
        if normalized == self.root_snapshot.agent_type_id:
            return self.root_snapshot
        cached = self.cache.get(normalized)
        if cached is not None:
            return cached
        if not self.provider_app_id or normalized not in self.agent_type_ids:
            raise InterAgentValidationError(f"Agent type `{normalized}` is not available to this orchestration.")
        definition_payload = _invoke_provider(
            self,
            alias="agent-catalog",
            body={"action": "get_agent_definition", "id": normalized},
        )
        definition = definition_payload.get("agent_definition")
        if not definition_payload.get("exists") or not isinstance(definition, dict):
            raise InterAgentValidationError(f"Agent type `{normalized}` is no longer available.")
        if str(definition.get("id") or "").strip() != normalized or definition.get("enabled") is False:
            raise InterAgentValidationError(f"Agent type `{normalized}` is disabled or mismatched.")
        prompt_payload = _invoke_provider(
            self,
            alias="agent-prompt-materializer",
            body={"action": "preview_prompt", "agent_type_id": normalized},
        )
        skill_catalog_app_id = _skill_catalog_app_id(self, definition, prompt_payload)
        snapshot = AgentParticipantSnapshot(
            agent_type_id=normalized,
            label=str(definition.get("name") or normalized).strip(),
            system_prompt=_with_root_active_context(
                str(prompt_payload.get("rendered") or "").strip(),
                self.root_system_prompt,
            ),
            skill_ids=_string_items(definition.get("skill_ids")),
            skill_catalog_app_id=skill_catalog_app_id,
            provider_id=self.provider_app_id,
            revision_id=(
                str(definition.get("revision_id") or definition.get("updated_at") or "").strip() or None
            ),
            metadata={
                "source": "orchestration_server_agent_catalog",
                "definition_updated_at": str(definition.get("updated_at") or "").strip(),
            },
        )
        self.cache[normalized] = snapshot
        return snapshot


def build_orchestration_agent_catalog(
    state: Any,
    *,
    workspace_id: str,
    created_by_user_id: str,
    root_session: Any,
    orchestrator: InterAgentParticipantRecord,
    start_path: Path,
) -> OrchestrationAgentCatalog:
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
        probe = OrchestrationAgentCatalog(
            root_snapshot=root_snapshot,
            prompt_entries=(),
            provider_app_id=provider_app_id,
            agent_type_ids=frozenset(),
            state=state,
            workspace_id=workspace_id,
            user=user,
            root_system_prompt=str(root_session.system_prompt or ""),
            start_path=start_path,
        )
        payload = _invoke_provider(
            probe,
            alias="agent-catalog",
            body={"action": "catalog.compact", "entity_type": "agent_type", "limit": 50},
        )
        items = [
            item
            for item in payload.get("agent_types", [])
            if isinstance(item, dict) and item.get("enabled") is not False and str(item.get("id") or "").strip()
        ]
        prompt_entries = tuple(
            _catalog_prompt_entry(item)
            for item in items
        )
        probe.prompt_entries = prompt_entries
        probe.agent_type_ids = frozenset(str(item["id"]).strip() for item in items)
        return probe
    except Exception:
        return OrchestrationAgentCatalog(
            root_snapshot=root_snapshot,
            prompt_entries=(f"{root_snapshot.agent_type_id}: {root_snapshot.label}",),
            provider_app_id=None,
            agent_type_ids=frozenset({root_snapshot.agent_type_id}),
            state=state,
            workspace_id=workspace_id,
            user=None,
            root_system_prompt=str(root_session.system_prompt or ""),
            start_path=start_path,
        )


def _root_snapshot(participant: InterAgentParticipantRecord) -> AgentParticipantSnapshot:
    document = participant.agent_snapshot if isinstance(participant.agent_snapshot, dict) else {}
    return AgentParticipantSnapshot(
        agent_type_id=str(document.get("agent_type_id") or participant.agent_type_id or "orchestrator"),
        label=str(document.get("label") or participant.label),
        system_prompt=str(document.get("system_prompt") or ""),
        skill_ids=_string_items(document.get("skill_ids")),
        skill_catalog_app_id=str(document.get("skill_catalog_app_id") or "skills"),
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
    selected = _string_items(dependency.get("selected_provider_app_ids"))
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


def _invoke_provider(catalog: OrchestrationAgentCatalog, *, alias: str, body: dict[str, Any]) -> dict[str, Any]:
    result = invoke_dependency_backend_request(
        catalog.state,
        workspace_id=catalog.workspace_id,
        app_id=CHAT_APP_ID,
        dependency_alias=alias,
        provider_app_id=catalog.provider_app_id,
        body=body,
        user=catalog.user,
        start_path=catalog.start_path,
    )
    payload = result.get("json") if isinstance(result.get("json"), dict) else result
    if not isinstance(payload, dict):
        raise InterAgentValidationError(f"Agent dependency `{alias}` returned an invalid payload.")
    return payload


def _skill_catalog_app_id(
    catalog: OrchestrationAgentCatalog,
    definition: dict[str, Any],
    prompt_payload: dict[str, Any],
) -> str:
    candidate = str(
        definition.get("skill_catalog_app_id")
        or prompt_payload.get("skill_catalog_app_id")
        or selected_runtime_skill_catalog_app_id_for_source_app(
            catalog.state.app_store,
            workspace_id=catalog.workspace_id,
            source_app_id=catalog.provider_app_id,
            user=catalog.user,
            workspace_store=catalog.state.workspace_store,
            start_path=catalog.start_path,
            allow_missing_source_app=True,
        )
        or catalog.root_snapshot.skill_catalog_app_id
        or ""
    ).strip()
    try:
        return validate_runtime_skill_catalog_provider_app_id(
            catalog.state.app_store,
            workspace_id=catalog.workspace_id,
            provider_app_id=candidate,
            user=catalog.user,
            workspace_store=catalog.state.workspace_store,
            start_path=catalog.start_path,
        )
    except AppHostingError as error:
        raise InterAgentValidationError(str(error)) from error


def _with_root_active_context(prompt: str, root_prompt: str) -> str:
    marker = f"\n\n{ACTIVE_APP_CONTEXT_HEADER}"
    index = root_prompt.rfind(marker)
    context = root_prompt[index + 2 :] if index >= 0 else ""
    return "\n\n".join(item for item in (prompt.strip(), context.strip()) if item)


def _catalog_prompt_entry(item: dict[str, Any]) -> str:
    identifier = str(item.get("id") or "").strip()
    name = " ".join(str(item.get("name") or identifier).split())
    description = " ".join(str(item.get("description") or "").split())[:240]
    return f"{identifier}: {name}" + (f" — {description}" if description else "")


def _string_items(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [text for item in value if (text := str(item or "").strip())]
