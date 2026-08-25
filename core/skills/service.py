"""Service helpers for the platform-managed skills layer."""

from __future__ import annotations

from pathlib import Path

from core.providers.provider_registry import ProviderRegistry
from core.runtime.runtime_session import RuntimeSessionRecord
from core.skills.catalog import DEFAULT_SKILL_CATALOG_APP_ID, list_workspace_skills, resolve_workspace_skills
from core.skills.materializer import materialize_skills_for_provider
from core.skills.models import SkillDefinition, SkillMaterialization


class SkillInvocationError(ValueError):
    """Reject an explicit skill invocation before provider dispatch."""

    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code


MAX_INVOKED_SKILLS_PER_TURN = 32


def normalize_invoked_skill_ids(invoked_skill_ids: list[str] | None) -> list[str]:
    """Normalize one bounded invocation receipt without resolving catalog data."""
    requested: list[str] = []
    seen: set[str] = set()
    for value in invoked_skill_ids or []:
        skill_id = str(value or "").strip()
        if not skill_id:
            raise SkillInvocationError("invalid_invoked_skill_id", "Invoked skill ids cannot be empty.")
        if skill_id in seen:
            continue
        if len(skill_id) > 160 or any(token in skill_id for token in ("/", "\\")) or skill_id in {".", ".."}:
            raise SkillInvocationError("invalid_invoked_skill_id", f"Invalid invoked skill id `{skill_id}`.")
        requested.append(skill_id)
        seen.add(skill_id)
    if len(requested) > MAX_INVOKED_SKILLS_PER_TURN:
        raise SkillInvocationError(
            "too_many_invoked_skills",
            f"A turn may invoke at most {MAX_INVOKED_SKILLS_PER_TURN} skills.",
        )
    return requested


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


def resolve_invoked_runtime_skills(
    session: RuntimeSessionRecord,
    invoked_skill_ids: list[str] | None,
    *,
    start_path: Path | None = None,
) -> list[SkillDefinition]:
    """Resolve enabled, session-allowed skill ids without trusting client paths."""
    requested = normalize_invoked_skill_ids(invoked_skill_ids)
    if not requested:
        return []
    allowed = set(session.skill_ids)
    denied = [skill_id for skill_id in requested if allowed and skill_id not in allowed]
    if denied:
        raise SkillInvocationError(
            "invoked_skill_not_allowed",
            f"Skill invocation is outside the session allowlist: {', '.join(denied)}",
        )
    try:
        return resolve_workspace_skills(
            workspace_id=session.workspace_id,
            skill_ids=requested,
            start_path=start_path,
            app_id=session.skill_catalog_app_id or DEFAULT_SKILL_CATALOG_APP_ID,
        )
    except ValueError as error:
        raise SkillInvocationError("invoked_skill_unavailable", str(error)) from error


def prepare_runtime_skills(
    registry: ProviderRegistry,
    *,
    provider_id: str,
    session: RuntimeSessionRecord,
    skills: list[SkillDefinition],
) -> list[SkillMaterialization]:
    """Install visible skill assets into the selected provider runtime home."""
    return materialize_skills_for_provider(registry, provider_id=provider_id, session=session, skills=skills)
