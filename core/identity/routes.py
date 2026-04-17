"""Identity-domain route placeholders for the initial v3 scaffold."""

from __future__ import annotations


def route_descriptions() -> dict[str, str]:
    """Describe the API surface this domain is expected to expose."""
    return {
        "users": "manage users",
        "sessions": "manage auth sessions",
        "credentials": "manage password credentials",
    }
