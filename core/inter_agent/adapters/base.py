"""Base contracts for experimental inter-agent adapters."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from core.inter_agent.errors import InterAgentOperationError
from core.inter_agent.events import InterAgentEventRecord, InterAgentVisibilityPlane
from core.inter_agent.models import InterAgentRunRecord


class InterAgentAdapterUnavailableError(InterAgentOperationError):
    """Raised when an experimental inter-agent adapter is disabled or missing."""


@dataclass(frozen=True)
class AdapterEventMappingContext:
    """Maverick-owned context required to project adapter events safely."""

    run: InterAgentRunRecord
    visibility_plane: InterAgentVisibilityPlane = "detail"
    sequence_start: int = 0
    event_id_prefix: str = "iaevt-adapter"
    created_at: datetime | None = None

    def event_id_for(self, index: int) -> str:
        """Return a deterministic local event id for a mapped adapter event."""
        prefix = self.event_id_prefix.strip() or "iaevt-adapter"
        return f"{prefix}-{index}"


class InterAgentAdapter(Protocol):
    """Small protocol shared by optional inter-agent adapters."""

    adapter_id: str

    def is_enabled(self) -> bool:
        """Return whether the adapter feature flag is enabled."""
        ...

    def is_available(self) -> bool:
        """Return whether the adapter can be used in this process."""
        ...

    def require_available(self) -> None:
        """Raise if the adapter is disabled or its optional package is missing."""
        ...

    def map_events(
        self,
        context: AdapterEventMappingContext,
        events: Iterable[object],
    ) -> list[InterAgentEventRecord]:
        """Project controlled adapter events into Maverick event records."""
        ...
