"""Workspace-scoped registry for app-owned embeddable widgets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.apps.errors import AppHostingError
from core.apps.models import ParsedAppContract, WidgetDeclaration, WorkspaceAppBindingRecord
from core.apps.store import AppStore
from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.authorization.service import can_mount_app_visibility
from core.identity.models import UserRecord


@dataclass(frozen=True)
class WidgetRegistryItem:
    """Public widget metadata exposed to host apps."""

    owner_app_id: str
    widget_id: str
    host: str
    content_kinds: list[str]
    frontend_mount: str
    actions: dict[str, bool]


@dataclass(frozen=True)
class ResolvedWidget:
    """Resolved widget metadata and filesystem mount owned by one app."""

    owner_app_id: str
    widget: WidgetDeclaration
    source_root: Path
    binding: WorkspaceAppBindingRecord
    parsed: ParsedAppContract


def widget_registry_item(owner_app_id: str, widget: WidgetDeclaration) -> WidgetRegistryItem:
    """Build the public registry item for one widget declaration."""
    return WidgetRegistryItem(
        owner_app_id=owner_app_id,
        widget_id=widget.widget_id,
        host=widget.host,
        content_kinds=list(widget.content_kinds),
        frontend_mount=f"/api/apps/widgets/{owner_app_id}/{widget.widget_id}/frontend/",
        actions={
            "backend": widget.actions.backend,
            "mcp": widget.actions.mcp,
            "cli": widget.actions.cli,
        },
    )


def list_workspace_widgets(
    store: AppStore,
    *,
    workspace_id: str,
    workspace_store=None,
    user: UserRecord | None = None,
    host: str | None = None,
    content_kind: str | None = None,
    start_path: Path | None = None,
) -> list[WidgetRegistryItem]:
    """List enabled widgets available to one workspace."""
    items: list[WidgetRegistryItem] = []
    for binding in enabled_workspace_app_bindings(store, workspace_id=workspace_id):
        try:
            _source_root, parsed = resolve_workspace_app_surface(store, binding=binding, start_path=start_path)
        except AppHostingError:
            continue
        if workspace_store is not None and not can_mount_app_visibility(
            workspace_store,
            user=user,
            workspace_id=workspace_id,
            platform_roles=parsed.contract.visibility.platform_roles,
            workspace_roles=parsed.contract.visibility.workspace_roles,
            capabilities=parsed.contract.visibility.capabilities,
        ):
            continue
        for widget in parsed.contract.widgets:
            if host is not None and widget.host != host:
                continue
            if content_kind is not None and content_kind not in widget.content_kinds:
                continue
            items.append(widget_registry_item(binding.app_id, widget))
    return sorted(items, key=lambda item: (item.owner_app_id, item.widget_id))


def resolve_workspace_widget(
    store: AppStore,
    *,
    workspace_id: str,
    owner_app_id: str,
    widget_id: str,
    workspace_store=None,
    user: UserRecord | None = None,
    start_path: Path | None = None,
) -> ResolvedWidget | None:
    """Resolve one enabled widget to its owner app source root."""
    for binding in enabled_workspace_app_bindings(store, workspace_id=workspace_id):
        if binding.app_id != owner_app_id:
            continue
        try:
            source_root, parsed = resolve_workspace_app_surface(store, binding=binding, start_path=start_path)
        except AppHostingError:
            return None
        if workspace_store is not None and not can_mount_app_visibility(
            workspace_store,
            user=user,
            workspace_id=workspace_id,
            platform_roles=parsed.contract.visibility.platform_roles,
            workspace_roles=parsed.contract.visibility.workspace_roles,
            capabilities=parsed.contract.visibility.capabilities,
        ):
            return None
        for widget in parsed.contract.widgets:
            if widget.widget_id == widget_id:
                return ResolvedWidget(
                    owner_app_id=binding.app_id,
                    widget=widget,
                    source_root=source_root,
                    binding=binding,
                    parsed=parsed,
                )
    return None
