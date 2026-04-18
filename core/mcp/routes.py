"""Route descriptions for the MCP domain."""

from __future__ import annotations


def route_descriptions() -> dict[str, str]:
    """Describe the public MCP domain surfaces at a high level."""
    return {
        "registry": "Platform-managed registry of core and app-contributed MCP tools.",
        "host": "Transport-agnostic MCP host surface built from the registry.",
    }
