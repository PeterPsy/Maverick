"""Provider-domain route placeholders for the initial v3 scaffold."""

from __future__ import annotations


def route_descriptions() -> dict[str, str]:
    """Describe the API surface this domain is expected to expose."""
    return {
        "registry": "list registered providers and capability metadata",
        "credentials": "bind provider secret references without exposing raw secrets",
        "selection": "configure and resolve workspace-scoped provider selection",
        "launch": "prepare runtime backend launch specs for provider adapters",
    }

