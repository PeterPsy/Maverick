"""Runtime-domain route placeholders for the initial v3 scaffold."""

from __future__ import annotations


def route_descriptions() -> dict[str, str]:
    """Describe the API surface this domain is expected to expose."""
    return {
        "sessions": "manage runtime sessions",
        "events": "read runtime events",
        "processes": "inspect runtime process state",
    }
