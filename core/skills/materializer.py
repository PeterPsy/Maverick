"""Provider-aware skill materialization for runtime homes."""

from __future__ import annotations

from core.providers.provider_registry import ProviderRegistry
from core.runtime.runtime_session import RuntimeSessionRecord
from core.skills.models import SkillDefinition, SkillMaterialization


def materialize_skills_for_provider(
    registry: ProviderRegistry,
    *,
    provider_id: str,
    session: RuntimeSessionRecord,
    skills: list[SkillDefinition],
) -> list[SkillMaterialization]:
    """Delegate runtime skill installation to the selected provider adapter."""
    adapter = registry.get_runtime_adapter(provider_id)
    return adapter.prepare_runtime_skills(session, skills)
