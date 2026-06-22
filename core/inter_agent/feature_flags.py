"""Feature flags for product-facing inter-agent surfaces."""

from __future__ import annotations

import os


MAVERICK_FEATURE_GROUP_CHAT = "MAVERICK_FEATURE_GROUP_CHAT"


def group_chat_mode_enabled() -> bool:
    """Return whether the F7 product-facing group_chat mode is enabled."""
    return os.environ.get(MAVERICK_FEATURE_GROUP_CHAT) == "1"
