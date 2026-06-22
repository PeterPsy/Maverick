"""Feature flags for product-facing inter-agent surfaces."""

from __future__ import annotations

import os

from core.inter_agent.errors import InterAgentValidationError


MAVERICK_FEATURE_GROUP_CHAT = "MAVERICK_FEATURE_GROUP_CHAT"
PUBLIC_INTER_AGENT_RUN_MODES = {"manager_tools", "sequential", "concurrent"}
FEATURE_GATED_INTER_AGENT_RUN_MODES = {"group_chat"}


def group_chat_mode_enabled() -> bool:
    """Return whether the F7 product-facing group_chat mode is enabled."""
    return os.environ.get(MAVERICK_FEATURE_GROUP_CHAT) == "1"


def validate_product_inter_agent_run_mode(mode: str) -> None:
    """Validate product-facing inter-agent mode exposure for public surfaces."""
    if mode in PUBLIC_INTER_AGENT_RUN_MODES:
        return
    if mode in FEATURE_GATED_INTER_AGENT_RUN_MODES and group_chat_mode_enabled():
        return
    if mode == "group_chat":
        raise InterAgentValidationError(f"Inter-agent group_chat mode requires {MAVERICK_FEATURE_GROUP_CHAT}=1.")
    raise InterAgentValidationError(f"Inter-agent run mode `{mode}` is not product-facing.")
