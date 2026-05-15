"""Service helpers for the platform-managed skills layer."""

from __future__ import annotations

from pathlib import Path

from core.providers.provider_registry import ProviderRegistry
from core.runtime.runtime_session import RuntimeSessionRecord
from core.skills.catalog import DEFAULT_SKILL_CATALOG_APP_ID, list_workspace_skills, resolve_workspace_skills
from core.skills.materializer import materialize_skills_for_provider
from core.skills.models import SkillDefinition, SkillMaterialization


def list_available_workspace_skills(
    *,
    workspace_id: str,
    start_path: Path | None = None,
    app_id: str = DEFAULT_SKILL_CATALOG_APP_ID,
) -> list[SkillDefinition]:
    """List workspace-owned skills available for runtime assignment."""
    return list_workspace_skills(workspace_id=workspace_id, start_path=start_path, app_id=app_id)


def resolve_runtime_skills(session: RuntimeSessionRecord, *, start_path: Path | None = None) -> list[SkillDefinition]:
    """Resolve explicit workspace-owned skill ids for validation and diagnostics."""
    return resolve_workspace_skills(
        workspace_id=session.workspace_id,
        skill_ids=session.skill_ids,
        start_path=start_path,
        app_id=session.skill_catalog_app_id or DEFAULT_SKILL_CATALOG_APP_ID,
    )


def prepare_runtime_skills(
    registry: ProviderRegistry,
    *,
    provider_id: str,
    session: RuntimeSessionRecord,
    skills: list[SkillDefinition],
) -> list[SkillMaterialization]:
    """Install visible skill assets into the selected provider runtime home."""
    return materialize_skills_for_provider(registry, provider_id=provider_id, session=session, skills=skills)
