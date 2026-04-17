"""Execution-policy route placeholders for the initial v3 scaffold."""

from __future__ import annotations


def route_descriptions() -> dict[str, str]:
    """Describe the API surface this domain is expected to expose."""
    return {
        "profiles": "resolve effective execution mode per workspace",
        "boundaries": "resolve runtime filesystem boundaries",
    }
