"""Service helpers for the platform-managed skills layer."""

from __future__ import annotations

from pathlib import Path

from core.apps.store import AppStore
from core.providers.provider_registry import ProviderRegistry
from core.runtime.runtime_session import RuntimeSessionRecord
from core.skills.catalog import list_core_skills, list_visible_skills, list_workspace_app_skills
from core.skills.materializer import materialize_skills_for_provider
from core.skills.models import SkillDefinition, SkillMaterialization


def list_available_core_skills(*, start_path: Path | None = None) -> list[SkillDefinition]:
    """List repository-local core skills."""
    return list_core_skills(start_path=start_path)


def list_available_workspace_skills(
    store: AppStore,
    *,
    workspace_id: str,
    start_path: Path | None = None,
) -> list[SkillDefinition]:
    """List app-contributed skills visible in one workspace."""
    return list_workspace_app_skills(store, workspace_id=workspace_id, start_path=start_path)


def list_visible_platform_skills(
    *,
    app_store: AppStore | None = None,
    workspace_id: str | None = None,
    start_path: Path | None = None,
) -> list[SkillDefinition]:
    """List all visible skills for the requested workspace context."""
    return list_visible_skills(app_store=app_store, workspace_id=workspace_id, start_path=start_path)


def prepare_runtime_skills(
    registry: ProviderRegistry,
    *,
    provider_id: str,
    session: RuntimeSessionRecord,
    skills: list[SkillDefinition],
) -> list[SkillMaterialization]:
    """Install visible skill assets into the selected provider runtime home."""
    return materialize_skills_for_provider(registry, provider_id=provider_id, session=session, skills=skills)
