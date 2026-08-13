"""Safe message-oriented runtime transcript contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


RuntimeTranscriptRole = Literal["human", "agent", "structured", "system"]
RuntimeTranscriptAuthorizationRelation = Literal["owner", "admin", "grant"]


@dataclass(frozen=True)
class RuntimeTranscriptReadContext:
    """Trusted actor context for transcript discovery and reads."""

    workspace_id: str
    user_id: str | None
    platform_role: str | None
    workspace_role: str | None
    caller_runtime_session_id: str | None


@dataclass
class RuntimeTranscriptMessage:
    """One user-visible message projected from runtime history."""

    message_id: str
    turn_id: str | None
    role: RuntimeTranscriptRole
    content: str
    status: str
    created_at: datetime
    source_event_ids: list[str] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    app_references: list[dict[str, Any]] = field(default_factory=list)
    structured_content: dict[str, Any] | None = None
    structured_content_truncated: bool = False
    redactions_applied: bool = False


@dataclass(frozen=True)
class RuntimeTranscriptProjection:
    """Complete in-memory projection plus explicit integrity warnings."""

    messages: list[RuntimeTranscriptMessage]
    warnings: list[str]
    complete: bool


@dataclass(frozen=True)
class RuntimeEventHistoryRead:
    """Historical runtime events loaded through the paged store contract."""

    events: list
    snapshot_newest_event_id: str | None
    warnings: list[str]
    complete: bool
