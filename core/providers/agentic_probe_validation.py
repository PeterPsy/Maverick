"""Per-response completion checks shared by operator-only protocol probes."""

from collections import Counter
from collections.abc import Sequence

from core.providers.agentic_protocol import AgenticModelEvent


def validate_probe_response(events: Sequence[AgenticModelEvent], *, final: bool) -> bool:
    """Never hide an extra call or a missing terminal behind previous responses."""
    if not events or len({event.request_id for event in events}) != 1:
        return False
    counts = Counter(event.event_type for event in events)
    if counts["error"] or any(event.error_code for event in events):
        return False
    if any(counts[kind] != 1 for kind in ("usage", "provider_state", "completed")):
        return False
    if any(
        (event.event_type == "usage" and event.usage is None)
        or (event.event_type == "provider_state" and event.provider_private_state is None)
        or (event.event_type == "tool_call" and event.tool_call is None)
        for event in events
    ):
        return False
    if final:
        return counts["tool_call"] == 0 and counts["text_final"] == 1 and any(
            event.event_type == "text_final" and bool((event.text or "").strip())
            for event in events
        )
    return counts["tool_call"] == 1
