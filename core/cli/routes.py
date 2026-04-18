"""Route descriptions for the CLI domain."""

from __future__ import annotations


def route_descriptions() -> dict[str, str]:
    """Describe the public CLI domain surfaces at a high level."""
    return {
        "registry": "Platform-managed registry of core and app-contributed CLI commands.",
        "runner": "Policy-aware command runner for trusted invocation contexts.",
    }
