"""Recovery-domain route placeholders."""

from __future__ import annotations


def route_descriptions() -> dict[str, str]:
    """Describe the API surface this domain is expected to expose."""
    return {
        "status": "inspect recovery state and latest health signals",
        "failed-start": "record failed-start diagnoses and recovery intents",
        "restart": "plan runtime restart or repair-first recovery actions",
        "health": "run or inspect runtime, provider, and app health checks",
        "service-boundary": "keep recovery operations available through a separable recovery surface",
    }
