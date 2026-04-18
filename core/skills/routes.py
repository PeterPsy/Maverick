"""Route descriptions for the skills domain."""

from __future__ import annotations


def route_descriptions() -> dict[str, str]:
    """Describe the public skills domain surfaces at a high level."""
    return {
        "catalog": "Catalog of core-owned and app-contributed instructional skills.",
        "materializer": "Provider-aware runtime skill installation that keeps skills instructional.",
    }
