"""App-domain route placeholders for the initial v3 scaffold."""

from __future__ import annotations


def route_descriptions() -> dict[str, str]:
    """Describe the API surface this domain is expected to expose."""
    return {
        "catalog": "list installed apps",
        "installations": "register app sources and workspace bindings",
        "mounts": "resolve app roots and workspace data roots",
        "lifecycle": "install, uninstall, reinstall, and purge app data",
    }
