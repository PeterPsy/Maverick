"""Best-effort private runtime submission diagnostics."""

from __future__ import annotations
from contextlib import suppress
import os
from typing import TYPE_CHECKING
from core.observability.service import append_platform_log
from core.runtime.runtime_session import RuntimeSessionRecord
if TYPE_CHECKING:
    from core.api.platform_state import PlatformState
    from core.providers.provider_registry import ProviderRegistry

def _debug_log_runtime_turn(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    provider_id: str,
    turn_id: str,
    message: str,
    payload: dict[str, object],
) -> None:
    """Write best-effort runtime turn diagnostics without changing execution behavior."""
    if not _runtime_turn_debug_logs_enabled():
        return
    with suppress(Exception):
        append_platform_log(
            log_plane="runtime",
            message=message,
            payload={
                "component": "runtime_turn_submission",
                "session_id": session.session_id,
                "turn_id": turn_id,
                **payload,
            },
            workspace_id=session.workspace_id,
            runtime_session_id=session.session_id,
            provider_id=provider_id,
            start_path=state.repository_root,
        )


def _runtime_turn_debug_logs_enabled() -> bool:
    return os.environ.get("LOOPINO_RUNTIME_TURN_DEBUG_LOGS", "").strip().lower() in {"1", "true", "yes", "on"}
