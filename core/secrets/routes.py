"""Secret-domain route placeholders."""

from __future__ import annotations


def route_descriptions() -> dict[str, str]:
    """Describe the API surface this domain is expected to expose."""
    return {
        "secrets": "create, rotate, disable, revoke, and inspect secret metadata",
        "bindings": "bind workspace, app, and provider secret references without exposing raw values",
        "resolution": "resolve secrets for authorized runtime use through controlled platform paths",
    }
