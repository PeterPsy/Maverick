"""App registry serialization for the hosted platform shell."""

from __future__ import annotations

from pathlib import Path

from core.api.platform_state import PlatformState
from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.identity.models import UserRecord


def user_can_mount_app(user: UserRecord | None, platform_roles: list[str] | None) -> bool:
    """Return whether one user may see and mount an app surface."""
    if not platform_roles:
        return True
    return user is not None and user.platform_role in platform_roles


def enabled_app_items(
    state: PlatformState,
    *,
    workspace_id: str,
    start_path: Path,
    user: UserRecord | None = None,
) -> list[dict[str, object]]:
    """Return enabled app registry items for one workspace."""
    items: list[dict[str, object]] = []
    for binding in enabled_workspace_app_bindings(state.app_store, workspace_id=workspace_id):
        source_root, parsed = resolve_workspace_app_surface(state.app_store, binding=binding, start_path=start_path)
        if not user_can_mount_app(user, parsed.contract.visibility.platform_roles):
            continue
        logo_path = source_root / "frontend" / "dist" / "maverick-icon-compact.png"
        item = {
            "app_id": parsed.app_id,
            "name": parsed.name,
            "version": parsed.version,
            "description": parsed.description,
            "publisher": parsed.publisher,
            "status": binding.status,
            "distribution_mode": parsed.contract.distribution.mode,
            "source_access": parsed.contract.distribution.source_access,
            "views": list(parsed.contract.capabilities.views),
            "logo": (
                {"kind": "image", "value": f"/apps/{parsed.app_id}/maverick-icon-compact.png"}
                if logo_path.exists()
                else None
            ),
            "frontend_mount": f"/apps/{parsed.app_id}/" if parsed.contract.entrypoints.frontend else "",
            "backend_mount": f"/api/apps/{parsed.app_id}/backend" if parsed.contract.entrypoints.backend else "",
        }
        if parsed.contract.visibility.platform_roles:
            item["visibility"] = {"platform_roles": parsed.contract.visibility.platform_roles}
        items.append(item)
    return items


def resolve_app_surface(state: PlatformState, *, workspace_id: str, app_id: str, start_path: Path):
    """Resolve one installed app to binding, source root, and parsed contract."""
    binding = state.app_store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    return binding, *resolve_workspace_app_surface(state.app_store, binding=binding, start_path=start_path)
