"""Workspace-domain route placeholders for the initial v3 scaffold."""

from __future__ import annotations


def route_descriptions() -> dict[str, str]:
    """Describe the API surface this domain is expected to expose."""
    return {
        "registry": "list and inspect workspaces",
        "bootstrap": "create and initialize workspace roots",
        "exports": "build workspace export manifests",
    }
