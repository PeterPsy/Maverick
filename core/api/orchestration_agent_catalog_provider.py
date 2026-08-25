"""Provider I/O and runtime-catalog validation for orchestration agents."""

from __future__ import annotations

from typing import Any

from core.api.orchestration_agent_catalog_models import OrchestrationAgentCatalogSource
from core.apps.errors import AppHostingError
from core.apps.runtime_requests import invoke_dependency_backend_request
from core.inter_agent.errors import InterAgentValidationError
from core.skills.runtime_catalog import (
    selected_runtime_skill_catalog_app_id_for_source_app,
    validate_runtime_skill_catalog_provider_app_id,
)


CHAT_APP_ID = "chat"
ACTIVE_APP_CONTEXT_HEADER = "Current shell context:"


def invoke_agent_provider(
    catalog: OrchestrationAgentCatalogSource,
    *,
    alias: str,
    body: dict[str, Any],
) -> dict[str, Any]:
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


def skill_catalog_app_id(
    catalog: OrchestrationAgentCatalogSource,
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


def string_items(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [text for item in value if (text := str(item or "").strip())]


def with_root_active_context(prompt: str, root_prompt: str) -> str:
    marker = f"\n\n{ACTIVE_APP_CONTEXT_HEADER}"
    index = root_prompt.rfind(marker)
    context = root_prompt[index + 2 :] if index >= 0 else ""
    return "\n\n".join(item for item in (prompt.strip(), context.strip()) if item)
