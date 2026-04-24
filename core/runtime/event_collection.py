"""Session-partitioned JSON collection for runtime event history."""

from __future__ import annotations

from pathlib import Path

from core.runtime.session_collection import RuntimeSessionJsonCollection


class RuntimeEventJsonCollection(RuntimeSessionJsonCollection):
    """Persist runtime events under each session runtime root."""

    def __init__(self, *, start_path: Path) -> None:
        super().__init__(start_path=start_path, filename="events.json", append_only_upserts=True)
