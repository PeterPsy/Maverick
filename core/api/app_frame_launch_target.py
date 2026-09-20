"""Resolve shell launch targets without confusing widgets with full frontends."""
from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

from core.api.app_frame_launch import authorized_app_surface, clean_app_launch_path, clean_relative_origin_url
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession
from core.api.widget_browser_launch_policy import nested_widget_context_matches, verify_nested_widget_context
from core.apps.errors import AppHostingError
from core.apps.models import WidgetDeclaration, WorkspaceAppBindingRecord
from core.apps.widgets import resolve_workspace_widget


_WIDGET_DOCUMENT = re.compile(r"^/api/apps/widgets/([^/]+)/([^/]+)/frontend/$")


def authorized_frame_launch_target(
    state: PlatformState, context: RequestSession, *, app_id: str, path: object, start_path: Path,
) -> tuple[WorkspaceAppBindingRecord, str, WidgetDeclaration | None]:
    """Return binding, canonical URL and optional declared widget under actor authority."""
    clean_path = clean_relative_origin_url(path)
    parsed = urlsplit(clean_path)
    match = _WIDGET_DOCUMENT.fullmatch(parsed.path)
    if match is None:
        binding, _root, _contract = authorized_app_surface(
            state, actor_user_id=context.user.user_id, workspace_id=context.workspace_id,
            app_id=app_id, start_path=start_path,
        )
        # Widget documents require their own declaration and signed context below.
        if not parsed.path.startswith(f"/apps/{binding.mount_app_id or binding.app_id}/"):
            raise AppHostingError("App frame launch requires a declared document surface.")
        return binding, clean_app_launch_path(clean_path, local_app_id=binding.app_id,
                                             mount_app_id=binding.mount_app_id or binding.app_id), None
    owner_id, widget_id = match.groups()
    if owner_id != app_id:
        raise AppHostingError("Widget frame owner does not match the requested app.")
    resolved = resolve_workspace_widget(
        state.app_store, workspace_id=context.workspace_id, owner_app_id=owner_id,
        widget_id=widget_id, workspace_store=state.workspace_store, user=context.user, start_path=start_path,
    )
    if resolved is None:
        raise AppHostingError("Widget frame declaration is unavailable.")
    try:
        fragment = parse_qs(parsed.fragment, max_num_fields=2, strict_parsing=True)
    except ValueError as error:
        raise AppHostingError("Invalid widget frame context.") from error
    tokens = fragment.get("context", [])
    if set(fragment) != {"context"} or len(tokens) != 1 or len(tokens[0]) > 16_384:
        raise AppHostingError("Widget frame requires one signed context.")
    if not nested_widget_context_matches(
        verify_nested_widget_context(tokens[0]), context=context, owner_app_id=owner_id,
        widget_id=widget_id, widget_host=resolved.widget.host, content_kinds=resolved.widget.content_kinds,
    ):
        raise AppHostingError("Widget frame context does not match its actor and declaration.")
    return resolved.binding, clean_path, resolved.widget
