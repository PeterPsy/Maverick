"""Microsoft Agent Framework adapter facade.

This module intentionally stops at F6 adapter scaffolding. It does not execute
MAF orchestrations, select providers, receive secrets, or own runtime sessions.
"""

from __future__ import annotations

from collections.abc import Iterable

from core.inter_agent.adapters.base import (
    AdapterEventMappingContext,
    InterAgentAdapterUnavailableError,
)
from core.inter_agent.adapters.group_chat import group_chat_records
from core.inter_agent.adapters.handoff import handoff_records
from core.inter_agent.adapters.magentic import magentic_records
from core.inter_agent.adapters.shared import (
    MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK,
    MafModules,
    _adapter_event_type,
    load_maf_modules,
)
from core.inter_agent.events import InterAgentEventRecord, validate_visibility_plane

__all__ = [
    "MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK",
    "MafAdapter",
    "MafModules",
    "load_maf_modules",
    "map_maf_events_to_inter_agent_records",
]


class MafAdapter:
    """Feature-flagged Microsoft Agent Framework adapter skeleton."""

    adapter_id = "maf"

    def is_enabled(self) -> bool:
        """Return whether the experimental MAF adapter flag is enabled."""
        import os

        return os.environ.get(MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK) == "1"

    def is_available(self) -> bool:
        """Return whether the flag is enabled and the optional MAF packages import."""
        try:
            self.require_available()
        except InterAgentAdapterUnavailableError:
            return False
        return True

    def require_available(self) -> None:
        """Raise when F6 MAF usage is disabled or optional packages are missing."""
        load_maf_modules()

    def map_events(
        self,
        context: AdapterEventMappingContext,
        events: Iterable[object],
    ) -> list[InterAgentEventRecord]:
        """Project controlled MAF events into Maverick event records."""
        self.require_available()
        return map_maf_events_to_inter_agent_records(context, events)


def map_maf_events_to_inter_agent_records(
    context: AdapterEventMappingContext,
    events: Iterable[object],
) -> list[InterAgentEventRecord]:
    """Map controlled MAF observations to safe Maverick event records."""
    visibility_plane = validate_visibility_plane(context.visibility_plane)
    records: list[InterAgentEventRecord] = []
    pending_handoffs: dict[str, str | None] = {}
    for source_index, event in enumerate(events, start=1):
        adapter_event_type = _adapter_event_type(event)
        if context.run.mode == "magentic_like":
            records.extend(
                magentic_records(
                    context,
                    event,
                    adapter_event_type=adapter_event_type,
                    visibility_plane=visibility_plane,
                    source_index=source_index,
                    mapped_index_start=len(records) + 1,
                )
            )
            continue
        projected = handoff_records(
            context,
            event,
            adapter_event_type=adapter_event_type,
            pending_handoffs=pending_handoffs,
            visibility_plane=visibility_plane,
            source_index=source_index,
            mapped_index=len(records) + 1,
        )
        if projected:
            records.extend(projected)
            continue
        records.extend(
            group_chat_records(
                context,
                event,
                adapter_event_type=adapter_event_type,
                visibility_plane=visibility_plane,
                source_index=source_index,
                mapped_index_start=len(records) + 1,
            )
        )
    return records
