"""Redaction-safe public models for Phase-0 remote containment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from core.runtime.agentic_inventory import RemoteAgenticSessionInventoryItem


ContainmentMode = Literal["dry_run", "apply"]


@dataclass(frozen=True)
class RemoteContainmentTarget:
    """One redaction-safe planned provider-CAS or session-lifecycle transition."""

    target_kind: Literal["binding", "profile", "certificate", "session"]
    identity: str
    workspace_id: str | None
    model_provider_id: str
    definition_id: str | None
    definition_revision: str | None
    current_revision: int | None
    current_status: str
    target_status: str
    target_digest: str


@dataclass(frozen=True)
class RemoteAgenticContainmentReport:
    """Deterministic, redaction-safe plan and execution result."""

    mode: ContainmentMode
    generated_at: datetime
    implementation_status: str
    dry_run_status: str
    operational_status: str
    counts: dict[str, int]
    binding_targets: tuple[RemoteContainmentTarget, ...]
    profile_targets: tuple[RemoteContainmentTarget, ...]
    certificate_targets: tuple[RemoteContainmentTarget, ...]
    session_targets: tuple[RemoteContainmentTarget, ...]
    session_inventory: tuple[RemoteAgenticSessionInventoryItem, ...]
    plan_digest: str
