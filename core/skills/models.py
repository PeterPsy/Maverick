"""Models for core-owned and app-contributed skill assets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


SkillOwnerKind = Literal["core", "app"]
SkillStatus = Literal["available", "disabled"]
SkillMaterializationStrategy = Literal["symlink", "copy"]


@dataclass(frozen=True)
class SkillDefinition:
    """Describe one skill asset visible to the platform."""

    skill_id: str
    local_skill_id: str
    name: str
    description: str
    source_root: str
    owner_kind: SkillOwnerKind
    owner_id: str
    workspace_id: str | None
    status: SkillStatus


@dataclass(frozen=True)
class SkillMaterialization:
    """Describe how one skill was installed into a provider runtime home."""

    provider_id: str
    skill_id: str
    source_root: str
    target_root: str
    strategy: SkillMaterializationStrategy
