"""Observability-domain route placeholders."""

from __future__ import annotations


def route_descriptions() -> dict[str, str]:
    """Describe the API surface this domain is expected to expose."""
    return {
        "events": "record and inspect structured platform and runtime events",
        "audit": "inspect structured audit records without leaking sensitive payloads",
        "metrics": "inspect health, recovery, and runtime metric samples",
        "logs": "manage installation-level and workspace-level log roots with retention and redaction",
    }
