"""Internal request authority propagated from an isolated app-frame session."""

from __future__ import annotations

import re
from typing import Any, Mapping, MutableMapping


APP_FRAME_PROXY_SCOPE_KEY = "maverick.app_frame_proxy"
APP_FRAME_APP_ID_SCOPE_KEY = "maverick.app_frame_app_id"
APP_FRAME_MOUNT_APP_ID_SCOPE_KEY = "maverick.app_frame_mount_app_id"
APP_FRAME_OWNER_MISMATCH_ERROR = "app_frame_owner_mismatch"

_APP_DOCUMENT_PATH = re.compile(r"^/apps/([^/]+)(?:/|$)")
_WIDGET_DOCUMENT_PATH = re.compile(
    r"^/api/apps/widgets/([^/]+)/[^/]+/frontend(?:/|$)"
)


def bind_app_frame_scope(
    scope: Mapping[str, Any],
    *,
    app_id: str,
    mount_app_id: str,
) -> dict[str, Any]:
    """Return a copied ASGI scope carrying the authenticated frame owner."""
    return {
        **scope,
        APP_FRAME_PROXY_SCOPE_KEY: True,
        APP_FRAME_APP_ID_SCOPE_KEY: app_id,
        APP_FRAME_MOUNT_APP_ID_SCOPE_KEY: mount_app_id,
    }


def copy_app_frame_scope_to_environ(
    scope: Mapping[str, Any],
    environ: MutableMapping[str, Any],
) -> None:
    """Copy only trusted internal app-frame authority into a WSGI environ."""
    if scope.get(APP_FRAME_PROXY_SCOPE_KEY) is not True:
        return
    environ[APP_FRAME_PROXY_SCOPE_KEY] = True
    for key in (APP_FRAME_APP_ID_SCOPE_KEY, APP_FRAME_MOUNT_APP_ID_SCOPE_KEY):
        value = scope.get(key)
        if isinstance(value, str):
            environ[key] = value


def app_frame_owner_matches(container: Mapping[str, Any], owner_app_id: str) -> bool:
    """Match a requested document owner to authenticated internal scope data."""
    if container.get(APP_FRAME_PROXY_SCOPE_KEY) is not True or not owner_app_id:
        return False
    return any(
        isinstance(candidate, str)
        and bool(candidate)
        and candidate == owner_app_id
        for candidate in (
            container.get(APP_FRAME_APP_ID_SCOPE_KEY),
            container.get(APP_FRAME_MOUNT_APP_ID_SCOPE_KEY),
        )
    )


def app_frame_path_matches_owner(
    path: str,
    *,
    app_id: str,
    mount_app_id: str,
) -> bool:
    """Reject app/widget document paths owned by another app-frame session."""
    owner_app_id = app_frame_document_owner(path)
    if owner_app_id is None:
        return True
    return any(
        bool(candidate) and candidate == owner_app_id
        for candidate in (app_id, mount_app_id)
    )


def app_frame_document_owner(path: str) -> str | None:
    """Return the owner encoded by an app or widget frontend document path."""
    for pattern in (_APP_DOCUMENT_PATH, _WIDGET_DOCUMENT_PATH):
        match = pattern.match(path)
        if match is not None:
            return match.group(1)
    return None
