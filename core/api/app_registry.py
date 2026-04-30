"""App registry serialization for the hosted platform shell."""

from __future__ import annotations

import logging
from pathlib import Path

from core.api.platform_state import PlatformState
from core.apps.errors import AppHostingError, WorkspaceAppBindingNotFoundError
from core.apps.models import AppVisibilityDeclaration
from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.authorization.service import can_mount_app_visibility
from core.identity.models import UserRecord


logger = logging.getLogger(__name__)


def user_can_mount_app(
    state: PlatformState,
    *,
    user: UserRecord | None,
    workspace_id: str,
    visibility: AppVisibilityDeclaration,
) -> bool:
    """Return whether one user may see and mount an app surface."""
    return can_mount_app_visibility(
        state.workspace_store,
        user=user,
        workspace_id=workspace_id,
        platform_roles=visibility.platform_roles,
        workspace_roles=visibility.workspace_roles,
        capabilities=visibility.capabilities,
    )


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
        try:
            source_root, parsed = resolve_workspace_app_surface(state.app_store, binding=binding, start_path=start_path)
        except AppHostingError:
            continue
        except Exception:
            logger.exception(
                "Skipping enabled app `%s` in workspace `%s` after unexpected surface resolution failure.",
                binding.app_id,
                workspace_id,
            )
            continue
        if not user_can_mount_app(state, user=user, workspace_id=workspace_id, visibility=parsed.contract.visibility):
            continue
        try:
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
                "provides": [
                    {
                        "interface": item.interface,
                        "version": item.version,
                        "description": item.description,
                        "surfaces": list(item.surfaces),
                    }
                    for item in parsed.contract.provides
                ],
                "requires": [
                    {
                        "alias": item.alias,
                        "interface": item.interface,
                        "version": item.version,
                        "required": item.required,
                        "cardinality": item.cardinality,
                        "description": item.description,
                    }
                    for item in parsed.contract.requires
                ],
                "logo": (
                    {"kind": "image", "value": f"/apps/{parsed.app_id}/maverick-icon-compact.png"}
                    if logo_path.exists()
                    else None
                ),
                "frontend_mount": f"/apps/{parsed.app_id}/" if parsed.contract.entrypoints.frontend else "",
                "backend_mount": f"/api/apps/{parsed.app_id}/backend" if parsed.contract.entrypoints.backend else "",
            }
            if parsed.contract.visibility.platform_roles or parsed.contract.visibility.workspace_roles or parsed.contract.visibility.capabilities:
                item["visibility"] = {
                    "platform_roles": parsed.contract.visibility.platform_roles,
                    "workspace_roles": parsed.contract.visibility.workspace_roles,
                    "capabilities": parsed.contract.visibility.capabilities,
                }
            items.append(item)
        except Exception:
            logger.exception(
                "Skipping enabled app `%s` in workspace `%s` after unexpected registry serialization failure.",
                binding.app_id,
                workspace_id,
            )
    return items


def resolve_app_surface(state: PlatformState, *, workspace_id: str, app_id: str, start_path: Path):
    """Resolve one installed app to binding, source root, and parsed contract."""
    binding = state.app_store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    if binding.status != "enabled":
        raise WorkspaceAppBindingNotFoundError(
            f"Workspace app `{app_id}` is not enabled in workspace `{workspace_id}`."
        )
    return binding, *resolve_workspace_app_surface(state.app_store, binding=binding, start_path=start_path)
